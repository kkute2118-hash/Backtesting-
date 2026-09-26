"""Create the ATI Lab server on Oracle Cloud's Always Free tier, via the API.

    pip install oci
    python deploy/oracle/provision.py            # create (or find) it
    python deploy/oracle/provision.py --dry-run  # show what it would do

Reads the Oracle API key and the app's settings from the environment, never
from arguments or files, so nothing secret lands in shell history:

    OCI_TENANCY_OCID  OCI_USER_OCID  OCI_FINGERPRINT  OCI_REGION  OCI_PRIVATE_KEY
    DHAN_CLIENT_ID  DHAN_PIN  DHAN_TOTP_SECRET  DHAN_ACCESS_TOKEN
    GH_BACKUP_TOKEN  (optional: GH_REPO, DB_BACKUP_BRANCH, GIT_TOKEN,
                      ANTHROPIC_API_KEY, TWELVEDATA_API_KEY, OCI_SSH_PUBLIC_KEY,
                      OCI_OCPUS, OCI_MEMORY_GB)

Safe to re-run: every resource is found by name before anything is created,
and an existing server is reported rather than duplicated. Everything is
created in the tenancy's root compartment, as Always Free expects.
"""

from __future__ import annotations

import argparse
import base64
import os
import pathlib
import re
import sys
import time

NAME = "ati-lab"
SHAPE = "VM.Standard.A1.Flex"
HERE = pathlib.Path(__file__).resolve().parent

# The values cloud-init.sh has a blank for, filled from the same-named
# environment variables when they are set.
SCRIPT_VARS = ("DHAN_CLIENT_ID", "DHAN_PIN", "DHAN_TOTP_SECRET", "DHAN_ACCESS_TOKEN",
               "GH_BACKUP_TOKEN", "GH_REPO", "DB_BACKUP_BRANCH", "GIT_TOKEN",
               "ANTHROPIC_API_KEY", "TWELVEDATA_API_KEY")


def say(msg: str) -> None:
    print(msg, flush=True)


def user_data() -> str:
    """cloud-init.sh with its fill-in block completed from the environment."""
    script = (HERE / "cloud-init.sh").read_text()
    for var in SCRIPT_VARS:
        value = os.environ.get(var, "")
        if not value:
            continue
        if '"' in value or "$" in value or "`" in value or "\\" in value:
            sys.exit(f"{var} contains a quote, $, ` or \\, which the script cannot carry safely.")
        script, n = re.subn(rf'^{var}="[^"\n]*"', f'{var}="{value}"', script, count=1,
                            flags=re.MULTILINE)
        if n != 1:
            sys.exit(f"cloud-init.sh has no {var}= line to fill in.")
    return script


def oci_config() -> dict:
    missing = [v for v in ("OCI_TENANCY_OCID", "OCI_USER_OCID", "OCI_FINGERPRINT",
                           "OCI_REGION", "OCI_PRIVATE_KEY") if not os.environ.get(v)]
    if missing:
        sys.exit("Missing environment variables: " + ", ".join(missing))
    key = os.environ["OCI_PRIVATE_KEY"].replace("\\n", "\n").strip() + "\n"
    return {
        "tenancy": os.environ["OCI_TENANCY_OCID"],
        "user": os.environ["OCI_USER_OCID"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "region": os.environ["OCI_REGION"],
        "key_content": key,
    }


def named(items, name):
    return next((i for i in items if i.display_name == name
                 and getattr(i, "lifecycle_state", "") not in ("TERMINATED", "TERMINATING")), None)


def ensure_network(vn, oci, compartment: str):
    """VCN, internet gateway, default route to it, ports 22 and 80, one subnet."""
    m = oci.core.models
    vcn = named(vn.list_vcns(compartment).data, f"{NAME}-vcn")
    if vcn is None:
        say("Creating the virtual network…")
        vcn = vn.create_vcn(m.CreateVcnDetails(
            compartment_id=compartment, display_name=f"{NAME}-vcn",
            cidr_blocks=["10.0.0.0/16"], dns_label="atilab")).data
        vcn = oci.wait_until(vn, vn.get_vcn(vcn.id), "lifecycle_state", "AVAILABLE").data

    igw = named(vn.list_internet_gateways(compartment, vcn_id=vcn.id).data, f"{NAME}-igw")
    if igw is None:
        say("Creating the internet gateway…")
        igw = vn.create_internet_gateway(m.CreateInternetGatewayDetails(
            compartment_id=compartment, vcn_id=vcn.id, is_enabled=True,
            display_name=f"{NAME}-igw")).data
        igw = oci.wait_until(vn, vn.get_internet_gateway(igw.id),
                             "lifecycle_state", "AVAILABLE").data

    vn.update_route_table(vcn.default_route_table_id, m.UpdateRouteTableDetails(route_rules=[
        m.RouteRule(destination="0.0.0.0/0", destination_type="CIDR_BLOCK",
                    network_entity_id=igw.id)]))

    def tcp(port):
        return m.IngressSecurityRule(
            protocol="6", source="0.0.0.0/0", source_type="CIDR_BLOCK",
            tcp_options=m.TcpOptions(destination_port_range=m.PortRange(min=port, max=port)))

    vn.update_security_list(vcn.default_security_list_id, m.UpdateSecurityListDetails(
        ingress_security_rules=[tcp(22), tcp(80)],
        egress_security_rules=[m.EgressSecurityRule(protocol="all", destination="0.0.0.0/0",
                                                    destination_type="CIDR_BLOCK")]))

    subnet = named(vn.list_subnets(compartment, vcn_id=vcn.id).data, f"{NAME}-subnet")
    if subnet is None:
        say("Creating the subnet…")
        subnet = vn.create_subnet(m.CreateSubnetDetails(
            compartment_id=compartment, vcn_id=vcn.id, display_name=f"{NAME}-subnet",
            cidr_block="10.0.0.0/24", dns_label="app",
            route_table_id=vcn.default_route_table_id,
            security_list_ids=[vcn.default_security_list_id],
            prohibit_public_ip_on_vnic=False)).data
        subnet = oci.wait_until(vn, vn.get_subnet(subnet.id),
                                "lifecycle_state", "AVAILABLE").data
    return subnet


def ubuntu_image(compute, compartment: str):
    for version in ("24.04", "22.04"):
        images = compute.list_images(
            compartment, operating_system="Canonical Ubuntu", operating_system_version=version,
            shape=SHAPE, sort_by="TIMECREATED", sort_order="DESC").data
        if images:
            return images[0]
    sys.exit("No Ubuntu image for the Ampere shape was found in this region.")


def public_ip(compute, vn, compartment: str, instance_id: str) -> str | None:
    for att in compute.list_vnic_attachments(compartment, instance_id=instance_id).data:
        if att.lifecycle_state == "ATTACHED":
            return vn.get_vnic(att.vnic_id).data.public_ip
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and the filled-in blanks, create nothing")
    args = parser.parse_args()

    script = user_data()
    filled = [v for v in SCRIPT_VARS if os.environ.get(v)]
    say(f"Setup script: {len(script):,} bytes; filled in from the environment: "
        f"{', '.join(filled) or 'nothing'}")
    if not os.environ.get("DHAN_CLIENT_ID"):
        say("Warning: DHAN_CLIENT_ID is not set, so the server will not be able to fetch data "
            "until it is added to /opt/ati-lab/deploy/oracle/.env there.")

    ocpus = float(os.environ.get("OCI_OCPUS", "2"))
    memory = float(os.environ.get("OCI_MEMORY_GB", "12"))
    if args.dry_run:
        say(f"Would create in {os.environ.get('OCI_REGION', '<OCI_REGION>')}: network "
            f"{NAME}-vcn with ports 22 and 80 open, and {SHAPE} '{NAME}' "
            f"({ocpus:g} OCPU, {memory:g} GB, Ubuntu, 50 GB disk).")
        return

    import oci

    config = oci_config()
    oci.config.validate_config(config)
    compartment = config["tenancy"]
    identity = oci.identity.IdentityClient(config)
    compute = oci.core.ComputeClient(config)
    vn = oci.core.VirtualNetworkClient(config)
    m = oci.core.models

    existing = named(compute.list_instances(compartment).data, NAME)
    if existing is not None:
        ip = public_ip(compute, vn, compartment, existing.id)
        say(f"Server '{NAME}' already exists ({existing.lifecycle_state}); public IP {ip}.")
        say(f"OPEN: http://{ip}")
        return

    subnet = ensure_network(vn, oci, compartment)
    image = ubuntu_image(compute, compartment)
    say(f"Image: {image.display_name}")

    metadata = {"user_data": base64.b64encode(script.encode()).decode()}
    if os.environ.get("OCI_SSH_PUBLIC_KEY"):
        metadata["ssh_authorized_keys"] = os.environ["OCI_SSH_PUBLIC_KEY"].strip()

    ads = [ad.name for ad in identity.list_availability_domains(compartment).data]
    instance = None
    for ad in ads:
        say(f"Launching in {ad}…")
        try:
            instance = compute.launch_instance(m.LaunchInstanceDetails(
                availability_domain=ad, compartment_id=compartment, display_name=NAME,
                shape=SHAPE,
                shape_config=m.LaunchInstanceShapeConfigDetails(ocpus=ocpus,
                                                                memory_in_gbs=memory),
                source_details=m.InstanceSourceViaImageDetails(
                    image_id=image.id, boot_volume_size_in_gbs=50),
                create_vnic_details=m.CreateVnicDetails(subnet_id=subnet.id,
                                                        assign_public_ip=True),
                metadata=metadata)).data
            break
        except oci.exceptions.ServiceError as exc:
            if "capacity" in str(exc.message).lower():
                say(f"  {ad}: out of capacity for free Ampere servers right now.")
                continue
            raise
    if instance is None:
        sys.exit("Every availability domain is out of Ampere capacity at the moment. "
                 "This is common; re-run this script later and it will pick up where it left off.")

    say("Waiting for the server to start…")
    instance = oci.wait_until(compute, compute.get_instance(instance.id), "lifecycle_state",
                              "RUNNING", max_wait_seconds=900).data
    ip = None
    for _ in range(30):
        ip = public_ip(compute, vn, compartment, instance.id)
        if ip:
            break
        time.sleep(5)
    say(f"Server '{NAME}' is running; public IP {ip}.")
    say("The app now installs and builds itself: allow 10-15 minutes.")
    say(f"OPEN: http://{ip}")


if __name__ == "__main__":
    main()
