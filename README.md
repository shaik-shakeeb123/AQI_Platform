# AQI Platform — Backend

An enterprise-grade Air Quality Intelligence (AQI) Platform backend API delivering real-time telemetry processing, CPCB-standard calculations, machine learning-powered predictions, and exposure-aware route optimization.

---

## Technical Stack

| Category | Technology | Purpose |
| :--- | :--- | :--- |
| **Language** | Python 3.10+ | Core runtime language |
| **Framework** | FastAPI | High-performance, asynchronous REST API framework |
| **Database** | PostgreSQL 16 | Primary relational database persistence |
| **ORM** | SQLAlchemy 2.0 | Declarative SQL schema execution and connection pooling |
| **Validation** | Pydantic v2 | Type-safe request/response payload validation and settings |
| **Forecasting** | LightGBM | Gradient Boosted Decision Trees for multi-horizon forecasts |
| **API Server** | Uvicorn | High-throughput ASGI server |
| **Integrations** | OpenAQ | Real-time Indian monitoring station telemetry data provider |
| **Integrations** | Open-Meteo | Meteorological forecasting and air quality fallback API |
| **Integrations** | Nominatim | Geographical address resolution and coordinate geocoding |

---

## Project Structure

```
AQI_Backend/
├── api_layer/          # Presentation and data access controller layer
│   ├── api/            # API endpoints (routes) and request/response validations (schemas)
│   └── repositories/   # Persistence layer executing database queries
├── services/           # Business layer orchestrating logic, fallbacks, and computations
├── database/           # Connection configurations and SQLAlchemy model definitions
├── ml_training/        # Feature engineering, model evaluation, and inference predictors
└── data_sync/          # Standalone background ingestion daemons and scheduler loops
```

---

## System Architecture

The backend implements a clean, layered architectural structure separating concerns and isolating external framework dependencies:

```
  [Client HTTP Request]
           │
           ▼
┌─────────────────────────┐
│   FastAPI Controllers   │  -- Presentation Layer
└─────────────────────────┘
           │
           ▼
┌─────────────────────────┐
│    Business Services    │  -- Application & Orchestration Layer
└─────────────────────────┘
     ┌─────┴──────────────┐
     ▼                    ▼
┌──────────────┐   ┌────────────────────────────────┐
│ Repositories │   │ ML Inference / External APIs   │  -- Core Domain Layer
└──────────────┘   └────────────────────────────────┘
     │
     ▼
┌──────────────┐
│  PostgreSQL  │  -- Persistence Layer
└──────────────┘
```

---

## Core Features

- [x] **Current AQI**: Real-time multi-station rolling average calculations aligned with CPCB guidelines.
- [x] **Historical AQI**: City-wide air quality records history filtering, sorting, and offset pagination.
- [x] **AQI Prediction**: Multi-horizon predictive forecasts (1h, 3h, 6h, 12h, 24h) using pre-trained LightGBM GBDTs.
- [x] **Weather Integration**: Current and hourly meteorological data integration.
- [x] **Health Recommendations**: Personalized health advice mapped to user health categories.
- [x] **Safe Outdoor Window**: Evaluates weather forecasts and simulated AQI trends to recommend the safest 2-hour outdoor windows.
- [x] **Route Optimization**: Geospatial route suggestions color-coded by localized pollutant exposure.
- [x] **Exposure Analysis**: Tracks localized personal exposure risk rating.
- [x] **Diagnostics**: Live health checking metrics evaluating DB, scheduler, ML models, and upstream APIs connectivity.

---

## API Modules

The REST API exposes the following functional modules:
*   **Air Quality Intelligence**: Telemetry retrieval, history sorting, ML forecasting, and exposure calculations.
*   **Weather**: City-specific weather conditions geocoding and parsing.
*   **Authentication**: Google OAuth token verification and JWT session key generation.
*   **System Diagnostics**: Service liveness status probes.

---

## Installation & Configuration

### Prerequisites
*   Python 3.10+
*   PostgreSQL 16

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/aqi-backend.git
cd aqi-backend
```

### 2. Configure Environment
Create a `.env` file in the root directory:
```ini
DATABASE_URL=postgresql://postgres:password@localhost:5432/aqi_platform
OPENAQ_API_KEY=your_openaq_api_key_here
JWT_SECRET_KEY=generate_a_secure_hex_key_here
GOOGLE_CLIENT_ID=your_google_oauth_client_id_here
DEBUG=True
```

### 3. Setup Virtual Environment & Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run the Application
Start the ASGI web server:
```bash
uvicorn api_layer.main:app --reload
```

---

## API Documentation

Interactive OpenAPI documentation is automatically compiled by FastAPI at startup:
*   **Swagger UI**: Available at `/docs` (interactive request sending).
*   **ReDoc**: Available at `/redoc` (structured documentation layout).

---

## Machine Learning Integration

*   **Offline Training**: Forecasting LightGBM models are pre-trained off-line and saved as serialized binary estimators.
*   **Decoupled Inference**: Preprocessing, feature engineering, and inference pipelines are managed in `ml_training/inference/` independently of REST routing concerns.
*   **Model Registry**: Lifespan startup hooks deserialize and cache models in memory for non-blocking prediction execution.

---

## Design Principles

- **Separation of Concerns**: Unidirectional layer dependency flow.
- **Repository Pattern**: Encapsulates data access behind repository interfaces.
- **Application Services**: Coordinates business logic and fallbacks separate from presentation logic.
- **SOLID Compliance**: Promotes modular testability and loose coupling.

---

## Future Improvements

*   **Docker Containerization**: Packaging the application for production cloud deployments.
*   **CI/CD Pipeline**: Automating test execution and vulnerability checks.
*   **Distributed Caching**: Redis integration to cache geocoding coordinates and OSRM route calculations.

---

## License

Distributed under the MIT License. See `LICENSE` for details.

---


