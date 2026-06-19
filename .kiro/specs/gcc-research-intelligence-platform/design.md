# Design Document - GCC Research Intelligence Platform

## Introduction

The GCC Research Intelligence Platform is a production-ready internal web application that enables sales and research teams to efficiently analyze companies for Global Capability Center (GCC) opportunities in India. The platform processes CSV files containing company data and leverages AI-powered research to determine GCC presence, suitability scores, and business insights while implementing intelligent caching to prevent duplicate research costs.

## System Architecture

### High-Level Architecture

The platform follows a modular, layered architecture optimized for Streamlit deployment:

```
┌─────────────────────────────────────────────────────────┐
│                    Streamlit Frontend                   │
├─────────────────────────────────────────────────────────┤
│                   Application Layer                     │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐   │
│  │Session Mgmt │ │Upload Proc  │ │Results Display  │   │
│  └─────────────┘ └─────────────┘ └─────────────────┘   │
├─────────────────────────────────────────────────────────┤
│                   Business Logic Layer                  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐   │
│  │Normalization│ │Research Eng │ │Cache Manager    │   │
│  │Engine       │ │             │ │                 │   │
│  └─────────────┘ └─────────────┘ └─────────────────┘   │
├─────────────────────────────────────────────────────────┤
│                    Data Layer                           │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐   │
│  │Supabase DB  │ │OpenAI API   │ │File System      │   │
│  └─────────────┘ └─────────────┘ └─────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Core Components

#### 1. Session Manager
**Purpose**: Handles authentication and session management
- Multi-user passcode authentication stored in database
- Session state management with expiration handling
- Secure access control for all platform features
- Automatic redirection on session expiry

#### 2. Upload Processor
**Purpose**: Manages CSV file uploads and validation
- Auto-detection of Company Name and Domain columns
- Manual column selection fallback
- Data validation and error reporting
- Support for various CSV formats and encodings

#### 3. Normalization Engine
**Purpose**: Creates consistent cache keys for deduplication
- Standardizes company names and domains
- Removes special characters and whitespace
- Converts to lowercase for consistency
- Handles missing domain data gracefully

#### 4. Cache Manager
**Purpose**: Manages research result caching to prevent duplicate AI costs
- Checks cache before expensive AI operations
- Stores results with normalized keys
- Maintains data integrity across users
- Provides cache hit indicators in UI

#### 5. Research Engine
**Purpose**: Interfaces with OpenAI GPT-4o for company analysis
- Determines GCC presence in India
- Calculates suitability scores (1-10)
- Identifies business pain points and expansion indicators
- Detects hiring signals and growth patterns
- Returns structured JSON responses
- Implements retry logic with exponential backoff

#### 6. Results Processor
**Purpose**: Manages sequential processing with live progress tracking
- Processes companies one at a time to manage rate limits
- Provides real-time progress updates
- Implements stop/resume functionality
- Preserves completed results during interruptions

#### 7. Export Manager
**Purpose**: Handles data export functionality
- Generates CSV exports with proper formatting
- Creates Excel files with formatted columns
- Preserves special characters and data integrity
- Provides immediate download capabilities

## Data Models

### Database Schema

#### Users Table
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    passcode VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);
```

#### Research Results Table
```sql
CREATE TABLE research_results (
    id SERIAL PRIMARY KEY,
    normalized_key VARCHAR(255) UNIQUE NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    company_domain VARCHAR(255),
    gcc_presence BOOLEAN,
    gcc_location VARCHAR(255),
    suitability_score INTEGER CHECK (suitability_score >= 1 AND suitability_score <= 10),
    business_pain_points TEXT,
    expansion_indicators TEXT,
    hiring_signals TEXT,
    research_summary TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    research_metadata JSONB
);

CREATE INDEX idx_research_normalized_key ON research_results(normalized_key);
CREATE INDEX idx_research_created_at ON research_results(created_at);
CREATE INDEX idx_research_suitability ON research_results(suitability_score);
```

#### Processing Sessions Table
```sql
CREATE TABLE processing_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) NOT NULL,
    total_companies INTEGER NOT NULL,
    processed_companies INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'running',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
```

### Data Transfer Objects

#### Company Record
```python
@dataclass
class CompanyRecord:
    name: str
    domain: Optional[str]
    normalized_key: str
    row_index: int
    
    def __post_init__(self):
        if not self.name.strip():
            raise ValueError("Company name cannot be empty")
```

#### Research Result
```python
@dataclass
class ResearchResult:
    company_name: str
    company_domain: Optional[str]
    gcc_presence: bool
    gcc_location: Optional[str]
    suitability_score: int
    business_pain_points: List[str]
    expansion_indicators: List[str]
    hiring_signals: List[str]
    research_summary: str
    is_cached: bool
    created_at: datetime
    
    def __post_init__(self):
        if not 1 <= self.suitability_score <= 10:
            raise ValueError("Suitability score must be between 1 and 10")
```

## Interface Specifications

### Streamlit User Interface

#### 1. Login Page
- Clean, professional login form
- Passcode input field with masking
- Error message display for invalid credentials
- Session state initialization on successful login

#### 2. Main Dashboard
- File upload widget with drag-and-drop support
- Processing progress indicators
- Real-time metrics display (processed, cached, errors)
- Stop/resume controls for batch processing

#### 3. Results View
- Interactive data table with search and filtering
- Column sorting capabilities
- Cache hit visual indicators
- Export buttons (CSV/Excel)
- Error display with retry options

#### 4. History Page
- Paginated historical results display
- Date range filtering
- Search functionality across all historical data
- Bulk export capabilities

### API Interfaces

#### OpenAI Research Prompt Template
```python
RESEARCH_PROMPT = """
Analyze the company '{company_name}' (domain: {company_domain}) for GCC opportunities in India.

Provide a JSON response with the following structure:
{
    "gcc_presence": boolean,
    "gcc_location": "string or null",
    "suitability_score": integer (1-10),
    "business_pain_points": ["string", "string"],
    "expansion_indicators": ["string", "string"],
    "hiring_signals": ["string", "string"],
    "research_summary": "string"
}

Research focus:
1. Does this company already have a GCC/development center in India?
2. Rate suitability for GCC establishment (1=poor, 10=excellent)
3. Identify business challenges that a GCC could solve
4. Look for signs of expansion or growth
5. Check for active hiring in tech/operations roles

Provide factual, research-based insights only.
"""
```

## Error Handling Strategy

### Error Categories and Responses

#### 1. Authentication Errors
- **Invalid Passcode**: Clear error message, retry allowed
- **Session Expiry**: Automatic redirect to login with notification
- **Database Connection**: User-friendly message, automatic retry

#### 2. File Upload Errors
- **Invalid File Format**: Specific format requirements displayed
- **Column Detection Failure**: Manual selection interface provided
- **Empty Data**: Clear validation messages with correction guidance

#### 3. Research Engine Errors
- **OpenAI API Failures**: Exponential backoff retry (3 attempts)
- **Rate Limiting**: Automatic queuing with progress indication
- **Invalid JSON Response**: Error logging, manual review flag

#### 4. Database Errors
- **Connection Failures**: Connection pooling with automatic reconnection
- **Query Timeouts**: Optimization suggestions and retry options
- **Constraint Violations**: Data validation improvement recommendations

### Retry Logic Implementation

```python
async def exponential_backoff_retry(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0
) -> Any:
    for attempt in range(max_attempts):
        try:
            return await func()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise e
            
            delay = min(base_delay * (2 ** attempt), max_delay)
            await asyncio.sleep(delay)
```

## Performance Considerations

### Caching Strategy
- **Primary Cache**: PostgreSQL with normalized keys
- **Session Cache**: In-memory Streamlit session state for UI performance
- **Cache Invalidation**: Time-based (30 days) and manual refresh options

### Rate Limiting Management
- Sequential processing to respect OpenAI rate limits
- Configurable delays between API calls
- Batch size optimization based on available quota

### Database Optimization
- Proper indexing on frequently queried columns
- Connection pooling for concurrent user support
- Query optimization for large result sets
- Pagination for historical data views

## Security Considerations

### Authentication Security
- Passcodes stored with secure hashing (bcrypt)
- Session tokens with secure random generation
- Automatic session expiration (24 hours)
- No client-side credential storage

### Data Protection
- Input sanitization for all user uploads
- SQL injection prevention through ORM usage
- API key protection through environment variables
- No sensitive data in logs or error messages

### Access Control
- Authentication required for all functionality
- No role-based access (all authenticated users have full access)
- Audit logging for all user actions
- Secure file upload validation

## Logging and Monitoring

### Log Structure
```python
LOG_FORMAT = {
    "timestamp": "ISO8601",
    "level": "INFO|WARN|ERROR",
    "component": "component_name",
    "user_session": "session_id",
    "action": "action_performed",
    "duration_ms": "execution_time",
    "details": "additional_context"
}
```

### Monitoring Metrics
- **Performance**: API response times, database query times
- **Usage**: Daily active users, companies processed, cache hit rates
- **Errors**: Error rates by component, retry success rates
- **Business**: Total research cost savings, user productivity metrics

## Deployment Architecture

### Streamlit Cloud Deployment
- Environment variables for sensitive configuration
- Requirements.txt with pinned versions
- Health check endpoints for monitoring
- Automatic deployment on main branch updates

### Configuration Management
```python
# .env structure
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key
OPENAI_API_KEY=your_openai_key
LOG_LEVEL=INFO
MAX_UPLOAD_SIZE_MB=50
CACHE_EXPIRY_DAYS=30
```

## Testing Strategy

### Unit Testing Approach
- **Normalization Engine**: Test key generation consistency
- **Cache Manager**: Test cache hit/miss logic
- **Data Validation**: Test input validation rules
- **Export Functions**: Test output format correctness

### Integration Testing
- **Database Operations**: Test CRUD operations with real database
- **OpenAI Integration**: Test API calls with mock responses
- **File Processing**: Test various CSV formats and edge cases
- **End-to-End Workflows**: Test complete user journeys

### Performance Testing
- **Load Testing**: Simulate multiple concurrent users
- **Large File Testing**: Test with maximum CSV file sizes
- **API Rate Limiting**: Test behavior under rate limits
- **Database Performance**: Test with large result sets

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Authentication Consistency

*For any* valid passcode stored in the database, authentication attempts with that passcode shall always succeed and create valid sessions

**Validates: Requirements 1.1, 1.2**

### Property 2: Authentication Rejection

*For any* invalid passcode (not stored in database or malformed), authentication attempts shall always fail with appropriate error messages

**Validates: Requirements 1.3**

### Property 3: Session Access Control

*For any* authenticated user session, access to all platform functionality shall be consistently granted while the session remains valid

**Validates: Requirements 1.4**

### Property 4: Column Detection Consistency

*For any* CSV file with recognizable company name and domain column patterns, auto-detection shall consistently identify the correct columns

**Validates: Requirements 2.2**

### Property 5: Data Validation Completeness

*For any* selected columns containing empty or invalid data, the validation process shall consistently reject the data with specific error messages

**Validates: Requirements 2.4, 2.5**

### Property 6: Normalization Consistency

*For any* company name and domain combination, the normalization engine shall always produce the same standardized cache key when given identical inputs

**Validates: Requirements 3.1, 3.4**

### Property 7: Cache Deduplication

*For any* company record with a normalized key that exists in the research cache, the system shall return cached results without making new AI API calls

**Validates: Requirements 4.2, 4.3**

### Property 8: Cache Integrity

*For any* new research result, the system shall immediately store it in the cache with the correct normalized key, making it available for future lookups

**Validates: Requirements 4.5**

### Property 9: Research Response Validation

*For any* research operation that completes successfully, the returned result shall be valid JSON containing all required fields with suitability scores between 1-10

**Validates: Requirements 5.3, 5.6**

### Property 10: Retry Logic Consistency

*For any* API failure scenario, the retry mechanism shall execute exactly three attempts with exponential backoff timing before final failure

**Validates: Requirements 5.7, 10.1**

### Property 11: Sequential Processing Order

*For any* list of companies to process, the results processor shall handle them in the exact order provided, one at a time

**Validates: Requirements 6.1**

### Property 12: Progress Tracking Accuracy

*For any* processing session, the progress metrics displayed shall accurately reflect the current state of completed, cached, and error counts

**Validates: Requirements 6.2, 6.5**

### Property 13: Stop Functionality Preservation

*For any* processing session that is stopped, all previously completed results shall be preserved and remain accessible

**Validates: Requirements 6.4**

### Property 14: Filtering Accuracy

*For any* set of research results and filter criteria (GCC status, suitability score), the filtered results shall contain only records that match all specified criteria

**Validates: Requirements 7.2**

### Property 15: Sorting Consistency

*For any* column in the results table, sorting operations shall consistently order all records according to the specified column values in the requested direction

**Validates: Requirements 7.3**

### Property 16: Export Data Completeness

*For any* set of research results selected for export, the generated CSV or Excel file shall contain all data fields with proper formatting and no data loss

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

### Property 17: Historical Search Accuracy

*For any* search query applied to historical results, the returned records shall contain only those that match the search criteria in any searchable field

**Validates: Requirements 9.3**

### Property 18: Date Range Filtering

*For any* date range filter applied to historical results, only records with creation timestamps within the specified range shall be returned

**Validates: Requirements 9.5**

### Property 19: Error Isolation

*For any* batch processing operation where individual companies fail research, the processor shall continue with remaining companies and preserve all successful results

**Validates: Requirements 10.4**

### Property 20: Logging Completeness

*For any* user action or system operation, appropriate log entries shall be created with timestamps, session identifiers, and relevant context information

**Validates: Requirements 11.1, 11.2**

## Implementation Notes

### Code Organization
```
src/
├── main.py                 # Streamlit app entry point
├── components/
│   ├── authentication.py   # Session management
│   ├── file_upload.py     # CSV processing
│   ├── research_engine.py # AI integration
│   └── results_display.py # UI components
├── core/
│   ├── normalization.py   # Key generation
│   ├── cache_manager.py   # Research caching
│   └── database.py        # Database operations
├── models/
│   ├── entities.py        # Data classes
│   └── schemas.py         # Database models
├── utils/
│   ├── config.py          # Configuration management
│   ├── logging.py         # Logging setup
│   └── validation.py      # Input validation
└── tests/
    ├── unit/              # Unit tests
    ├── integration/       # Integration tests
    └── fixtures/          # Test data
```

### Development Guidelines
- Use type hints throughout the codebase
- Implement comprehensive docstrings for all public functions
- Follow PEP 8 coding standards
- Use dependency injection for testability
- Implement proper error handling and logging
- Use async/await for I/O operations where beneficial

The platform is designed to be maintainable, scalable, and production-ready while providing an intuitive user experience for internal sales and research teams.