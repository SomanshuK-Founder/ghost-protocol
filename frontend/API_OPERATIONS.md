# Generated operation map

Source: accepted ghost-app-v1 OpenAPI; regenerate with npm run generate:api.
All 19 browser operations have frontend interactions in Phases 1–3. Public health is not consumed by the app client. Operation pages organize the bounded returned set; only tasks, documents and timeline expose backend cursors.

| Screen / scope | Method and path | Exact operation ID | Security |
| --- | --- | --- | --- |
| Approval center / exact review / explicit decision and revocation | GET /api/app/v1/approvals | approvals_api_app_v1_approvals_get | [{"AppSession":[]}] |
| Approval center / exact review / explicit decision and revocation | GET /api/app/v1/approvals/{approval_ref} | approval_detail_api_app_v1_approvals__approval_ref__get | [{"AppSession":[]}] |
| Approval center / exact review / explicit decision and revocation | POST /api/app/v1/approvals/{approval_ref}/decision | decision_api_app_v1_approvals__approval_ref__decision_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Approval center / exact review / explicit decision and revocation | POST /api/app/v1/approvals/{approval_ref}/revoke | revoke_api_app_v1_approvals__approval_ref__revoke_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Document catalog / task composer | GET /api/app/v1/documents | documents_api_app_v1_documents_get | [{"AppSession":[]}] |
| Pairing / session | GET /api/app/v1/session | session_status_api_app_v1_session_get | [] |
| Pairing / session | POST /api/app/v1/session/login | login_api_app_v1_session_login_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Pairing / session | POST /api/app/v1/session/logout | logout_api_app_v1_session_logout_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Dashboard / task workspace | GET /api/app/v1/tasks | listing_api_app_v1_tasks_get | [{"AppSession":[]}] |
| Dashboard / task workspace | POST /api/app/v1/tasks | create_api_app_v1_tasks_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Dashboard / task workspace | GET /api/app/v1/tasks/{task_ref} | detail_api_app_v1_tasks__task_ref__get | [{"AppSession":[]}] |
| Task workspace / confirmed cancellation | POST /api/app/v1/tasks/{task_ref}/cancel | cancel_api_app_v1_tasks__task_ref__cancel_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Operation history / exact record | GET /api/app/v1/tasks/{task_ref}/operations | operations_api_app_v1_tasks__task_ref__operations_get | [{"AppSession":[]}] |
| Operation history / exact record | GET /api/app/v1/tasks/{task_ref}/operations/{operation_ref} | operation_api_app_v1_tasks__task_ref__operations__operation_ref__get | [{"AppSession":[]}] |
| Dashboard / task workspace | GET /api/app/v1/tasks/{task_ref}/planning | planning_status_api_app_v1_tasks__task_ref__planning_get | [{"AppSession":[]}] |
| Dashboard / task workspace | POST /api/app/v1/tasks/{task_ref}/planning | planning_api_app_v1_tasks__task_ref__planning_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Audit explorer / task preview | GET /api/app/v1/tasks/{task_ref}/timeline | timeline_api_app_v1_tasks__task_ref__timeline_get | [{"AppSession":[]}] |
| Dashboard / task workspace | GET /api/app/v1/tasks/{task_ref}/workflow | workflow_api_app_v1_tasks__task_ref__workflow_get | [{"AppSession":[]}] |
| Task workspace / separate safe continuation | POST /api/app/v1/tasks/{task_ref}/workflow/continue | continuation_api_app_v1_tasks__task_ref__workflow_continue_post | [{"AppSession":[],"CsrfHeader":[]}] |
| Public liveness (not consumed by app client) | GET /health | health_health_get | [] |

## Exact request and response inventory

### approvals_api_app_v1_approvals_get

GET /api/app/v1/approvals

- Request: No JSON body
- Parameters: query task_ref (required)
- Responses: 200: AppSuccess_ApprovalList_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### approval_detail_api_app_v1_approvals__approval_ref__get

GET /api/app/v1/approvals/{approval_ref}

- Request: No JSON body
- Parameters: path approval_ref (required)
- Responses: 200: AppSuccess_ApprovalDetail_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### decision_api_app_v1_approvals__approval_ref__decision_post

POST /api/app/v1/approvals/{approval_ref}/decision

- Request: ApprovalDecision
- Parameters: path approval_ref (required), header Idempotency-Key (required), header Origin (required)
- Responses: 200: AppSuccess_ApprovalMutation_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### revoke_api_app_v1_approvals__approval_ref__revoke_post

POST /api/app/v1/approvals/{approval_ref}/revoke

- Request: IdentityModel
- Parameters: path approval_ref (required), header Idempotency-Key (required), header Origin (required)
- Responses: 200: AppSuccess_ApprovalMutation_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### documents_api_app_v1_documents_get

GET /api/app/v1/documents

- Request: No JSON body
- Parameters: query limit (optional), query cursor (optional)
- Responses: 200: AppSuccess_AppPage_DocumentMetadata__; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### session_status_api_app_v1_session_get

GET /api/app/v1/session

- Request: No JSON body
- Parameters: None
- Responses: 200: SessionSuccess; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure

### login_api_app_v1_session_login_post

POST /api/app/v1/session/login

- Request: LoginRequest
- Parameters: header Origin (required)
- Responses: 200: SessionSuccess; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure

### logout_api_app_v1_session_logout_post

POST /api/app/v1/session/logout

- Request: IdentityModel
- Parameters: header Origin (required)
- Responses: 204: No JSON body; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure

### listing_api_app_v1_tasks_get

GET /api/app/v1/tasks

- Request: No JSON body
- Parameters: query limit (optional), query cursor (optional)
- Responses: 200: AppSuccess_TaskPage_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### create_api_app_v1_tasks_post

POST /api/app/v1/tasks

- Request: TaskCreate
- Parameters: header Idempotency-Key (required), header Origin (required)
- Responses: 200: AppSuccess_TaskDetail_; 201: AppSuccess_TaskDetail_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### detail_api_app_v1_tasks__task_ref__get

GET /api/app/v1/tasks/{task_ref}

- Request: No JSON body
- Parameters: path task_ref (required)
- Responses: 200: AppSuccess_TaskDetail_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### cancel_api_app_v1_tasks__task_ref__cancel_post

POST /api/app/v1/tasks/{task_ref}/cancel

- Request: IdentityModel
- Parameters: path task_ref (required), header Idempotency-Key (required), header Origin (required)
- Responses: 200: AppSuccess_CancelResult_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### operations_api_app_v1_tasks__task_ref__operations_get

GET /api/app/v1/tasks/{task_ref}/operations

- Request: No JSON body
- Parameters: path task_ref (required)
- Responses: 200: AppSuccess_OperationList_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### operation_api_app_v1_tasks__task_ref__operations__operation_ref__get

GET /api/app/v1/tasks/{task_ref}/operations/{operation_ref}

- Request: No JSON body
- Parameters: path task_ref (required), path operation_ref (required)
- Responses: 200: AppSuccess_OperationView_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### planning_status_api_app_v1_tasks__task_ref__planning_get

GET /api/app/v1/tasks/{task_ref}/planning

- Request: No JSON body
- Parameters: path task_ref (required)
- Responses: 200: AppSuccess_PlanningView_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### planning_api_app_v1_tasks__task_ref__planning_post

POST /api/app/v1/tasks/{task_ref}/planning

- Request: PlanningStart
- Parameters: path task_ref (required), header Idempotency-Key (required), header Origin (required)
- Responses: 200: AppSuccess_PlanningView_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### timeline_api_app_v1_tasks__task_ref__timeline_get

GET /api/app/v1/tasks/{task_ref}/timeline

- Request: No JSON body
- Parameters: path task_ref (required), query limit (optional), query cursor (optional)
- Responses: 200: AppSuccess_AppPage_TimelineItem__; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### workflow_api_app_v1_tasks__task_ref__workflow_get

GET /api/app/v1/tasks/{task_ref}/workflow

- Request: No JSON body
- Parameters: path task_ref (required)
- Responses: 200: AppSuccess_WorkflowView_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### continuation_api_app_v1_tasks__task_ref__workflow_continue_post

POST /api/app/v1/tasks/{task_ref}/workflow/continue

- Request: IdentityModel
- Parameters: path task_ref (required), header Idempotency-Key (required), header Origin (required)
- Responses: 200: AppSuccess_WorkflowView_; 400: AppFailure; 401: AppFailure; 403: AppFailure; 404: AppFailure; 409: AppFailure; 413: AppFailure; 415: AppFailure; 422: AppFailure; 429: AppFailure; 500: AppFailure; 503: AppFailure; 504: AppFailure

### health_health_get

GET /health

- Request: No JSON body
- Parameters: None
- Responses: 200: HealthResponse
