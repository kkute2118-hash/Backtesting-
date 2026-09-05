"""v1 API surface.

Routes are grouped by domain rather than by page so the frontend can compose
them freely — the dashboard reads market + forward + learning, and the scanner
page reads scanner + universes + presets.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (backtest_routes, data_routes, forward_routes,
                                  jobs_routes, learning_routes, market_routes,
                                  product_routes, research_routes,
                                  scanner_routes, stocks_routes, system)

api_router = APIRouter()
api_router.include_router(system.router, tags=["system"])
api_router.include_router(jobs_routes.router, tags=["jobs"])
api_router.include_router(market_routes.router, tags=["market"])
api_router.include_router(scanner_routes.router, tags=["scanner"])
api_router.include_router(stocks_routes.router, tags=["stocks"])
api_router.include_router(forward_routes.router, tags=["forward"])
api_router.include_router(product_routes.router, tags=["watchlists", "presets"])
api_router.include_router(learning_routes.router, tags=["learning"])
api_router.include_router(backtest_routes.router, tags=["backtest"])
api_router.include_router(data_routes.router, tags=["data"])
api_router.include_router(research_routes.router, tags=["research"])
