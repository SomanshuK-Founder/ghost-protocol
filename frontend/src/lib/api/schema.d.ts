export interface paths {
    "/api/app/v1/approvals": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Approvals
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["approvals_api_app_v1_approvals_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/approvals/{approval_ref}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Approval Detail
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["approval_detail_api_app_v1_approvals__approval_ref__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/approvals/{approval_ref}/decision": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Decision
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["decision_api_app_v1_approvals__approval_ref__decision_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/approvals/{approval_ref}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revoke
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["revoke_api_app_v1_approvals__approval_ref__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/documents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Documents
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["documents_api_app_v1_documents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Session Status
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["session_status_api_app_v1_session_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/session/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["login_api_app_v1_session_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/session/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["logout_api_app_v1_session_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Listing
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["listing_api_app_v1_tasks_get"];
        put?: never;
        /**
         * Create
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["create_api_app_v1_tasks_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Detail
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["detail_api_app_v1_tasks__task_ref__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cancel
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["cancel_api_app_v1_tasks__task_ref__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/operations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Operations
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["operations_api_app_v1_tasks__task_ref__operations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/operations/{operation_ref}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Operation
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["operation_api_app_v1_tasks__task_ref__operations__operation_ref__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/planning": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Planning Status
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["planning_status_api_app_v1_tasks__task_ref__planning_get"];
        put?: never;
        /**
         * Planning
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["planning_api_app_v1_tasks__task_ref__planning_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Timeline
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["timeline_api_app_v1_tasks__task_ref__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/workflow": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Workflow
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        get: operations["workflow_api_app_v1_tasks__task_ref__workflow_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/app/v1/tasks/{task_ref}/workflow/continue": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Continuation
         * @description LOCAL_DEMO is disabled by default and supports one owner/process on literal loopback only. Owner identity is server-derived. No browser bearer, owner, role or proxy headers. All reads validate Host/Origin/peer; POST requires the exact configured Origin and X-Ghost-CSRF bound to the HttpOnly SameSite=Strict preauth/session cookie. HTTPS uses __Host-ghost_session with Secure; explicit HTTP loopback uses ghost_demo_session without Secure. Cookies have Path=/ and no Domain. Expired/revoked sessions cannot access private results. Responses are no-store. Approval and metadata continuation never dispatch; UNKNOWN requires reconciliation, never an automatic resend. Catalog metadata does not authorize protected content.
         */
        post: operations["continuation_api_app_v1_tasks__task_ref__workflow_continue_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Check API liveness
         * @description Liveness only; no database/model/sandbox readiness claim.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** AnonymousSession */
        AnonymousSession: {
            /** Absolute Expires At */
            absolute_expires_at: null;
            /**
             * Authenticated
             * @default false
             * @constant
             */
            authenticated: false;
            /** Csrf Token */
            csrf_token: string;
            /** Idle Expires At */
            idle_expires_at: null;
            /**
             * Mode
             * @default LOCAL_DEMO
             * @constant
             */
            mode: "LOCAL_DEMO";
            /** Owner */
            owner: null;
        };
        /** AppErrorDetail */
        AppErrorDetail: {
            /** Code */
            code: ("AUTH_NOT_CONFIGURED" | "AUTH_RATE_LIMITED" | "LOGIN_FAILED" | "SESSION_REQUIRED" | "SESSION_EXPIRED" | "CSRF_INVALID" | "ORIGIN_FORBIDDEN" | "CREDENTIAL_HEADER_FORBIDDEN" | "INVALID_REQUEST" | "MALFORMED_JSON" | "DUPLICATE_JSON_FIELD" | "PAYLOAD_TOO_LARGE" | "UNSUPPORTED_MEDIA_TYPE" | "UNEXPECTED_IDEMPOTENCY_KEY" | "NOT_FOUND") | ("INVALID_CURSOR" | "IDEMPOTENCY_KEY_REQUIRED" | "IDEMPOTENCY_KEY_INVALID" | "IDEMPOTENCY_CONFLICT" | "COMMAND_IN_PROGRESS" | "COMMAND_UNCERTAIN" | "TASK_NOT_ACTIVE" | "PLANNING_ALREADY_STARTED" | "CAPACITY_EXCEEDED" | "INTERNAL_ERROR" | "BACKEND_UNAVAILABLE" | "HOST_UNAVAILABLE" | "COMMAND_TIMEOUT" | "APPROVAL_STATE_CONFLICT" | "WORKFLOW_NOT_READY" | "WORKFLOW_DENIED" | "RECONCILIATION_REQUIRED");
            /** Command Ref */
            command_ref: string | null;
            /**
             * Command Uncertain
             * @default false
             */
            command_uncertain: boolean;
            /** Correlation Ref */
            correlation_ref: string;
            /**
             * Execution Uncertain
             * @default false
             */
            execution_uncertain: boolean;
            /**
             * Message
             * @default Request cannot be processed
             * @constant
             */
            message: "Request cannot be processed";
            /** Reason Code */
            reason_code: null;
            /**
             * Reconciliation Required
             * @default false
             */
            reconciliation_required: boolean;
        };
        /** AppFailure */
        AppFailure: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            error: components["schemas"]["AppErrorDetail"];
        };
        /** AppPage[DocumentMetadata] */
        AppPage_DocumentMetadata_: {
            /** Items */
            items: components["schemas"]["DocumentMetadata"][];
            /** Next Cursor */
            next_cursor: string | null;
            /**
             * Snapshot At
             * Format: date-time
             */
            snapshot_at: string;
        };
        /** AppPage[TimelineItem] */
        AppPage_TimelineItem_: {
            /** Items */
            items: components["schemas"]["TimelineItem"][];
            /** Next Cursor */
            next_cursor: string | null;
            /**
             * Snapshot At
             * Format: date-time
             */
            snapshot_at: string;
        };
        /** AppSuccess[AppPage[DocumentMetadata]] */
        AppSuccess_AppPage_DocumentMetadata__: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["AppPage_DocumentMetadata_"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[AppPage[TimelineItem]] */
        AppSuccess_AppPage_TimelineItem__: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["AppPage_TimelineItem_"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[ApprovalDetail] */
        AppSuccess_ApprovalDetail_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["ApprovalDetail"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[ApprovalList] */
        AppSuccess_ApprovalList_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["ApprovalList"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[ApprovalMutation] */
        AppSuccess_ApprovalMutation_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["ApprovalMutation"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[CancelResult] */
        AppSuccess_CancelResult_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["CancelResult"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[OperationList] */
        AppSuccess_OperationList_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["OperationList"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[OperationView] */
        AppSuccess_OperationView_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["OperationView"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[PlanningView] */
        AppSuccess_PlanningView_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["PlanningView"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[TaskDetail] */
        AppSuccess_TaskDetail_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["TaskDetail"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[TaskPage] */
        AppSuccess_TaskPage_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["TaskPage"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** AppSuccess[WorkflowView] */
        AppSuccess_WorkflowView_: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            data: components["schemas"]["WorkflowView"];
            /**
             * Replayed
             * @default false
             */
            replayed: boolean;
        };
        /** ApprovalDecision */
        ApprovalDecision: {
            /**
             * Resolution
             * @enum {string}
             */
            resolution: "APPROVE" | "REJECT";
        };
        /** ApprovalDetail */
        ApprovalDetail: {
            /**
             * Action
             * @enum {string}
             */
            action: "files.list_authorized" | "files.read" | "email.draft" | "email.send" | "tasks.list";
            /** Approval Ref */
            approval_ref: string;
            /** Arguments */
            arguments: components["schemas"]["FileArguments"] | components["schemas"]["EmailArguments"];
            /** Binding Digest */
            binding_digest: string;
            /** Consumed */
            consumed: boolean;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** In Flight */
            in_flight: boolean;
            /** Operation Ref */
            operation_ref: string;
            provenance: components["schemas"]["Provenance"];
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "summarize_document" | "prepare_email" | "summarize_and_prepare_email" | "morning_brief" | "answer_question";
            /** Request Id */
            request_id: string;
            /** Resource Versions */
            resource_versions: components["schemas"]["ResourceVersion"][];
            /**
             * State
             * @enum {string}
             */
            state: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "REVOKED";
            /** Task Ref */
            task_ref: string;
        };
        /** ApprovalList */
        ApprovalList: {
            /** Items */
            items: components["schemas"]["ApprovalSummary"][];
        };
        /** ApprovalMutation */
        ApprovalMutation: {
            approval: components["schemas"]["ApprovalSummary"];
            /** In Flight */
            in_flight: boolean;
        };
        /** ApprovalSummary */
        ApprovalSummary: {
            /** Approval Ref */
            approval_ref: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** Operation Ref */
            operation_ref: string;
            /** Request Id */
            request_id: string;
            /**
             * State
             * @enum {string}
             */
            state: "PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "REVOKED";
            /** Task Ref */
            task_ref: string;
        };
        /** CancelResult */
        CancelResult: {
            /** In Flight */
            in_flight: boolean;
            task: components["schemas"]["TaskSummary"];
        };
        /** DocumentMetadata */
        DocumentMetadata: {
            /**
             * Classification
             * @enum {string}
             */
            classification: "PRIVATE_ORIGINAL" | "SHAREABLE";
            /** Display Name */
            display_name: string;
            /** Resource Id */
            resource_id: string;
            /**
             * Resource Type
             * @default SYNTHETIC_TEXT
             * @constant
             */
            resource_type: "SYNTHETIC_TEXT";
            /**
             * Synthetic
             * @default true
             * @constant
             */
            synthetic: true;
            /** Version Ref */
            version_ref: string;
        };
        /** EmailArguments */
        EmailArguments: {
            /**
             * Attachment Resource Ids
             * @default []
             */
            attachment_resource_ids: string[];
            /** Body */
            body: string;
            /** Recipient */
            recipient: string;
            /** Subject */
            subject: string;
        };
        /** FileArguments */
        FileArguments: {
            /** Resource Id */
            resource_id: string;
        };
        /** HealthResponse */
        HealthResponse: {
            /** Database */
            database?: string | null;
            /** Status */
            status: string;
        };
        /** IdentityModel */
        IdentityModel: Record<string, never>;
        /** LoginRequest */
        LoginRequest: {
            /**
             * Pairing Code
             * Format: password
             */
            pairing_code: string;
        };
        /** OperationList */
        OperationList: {
            /** Items */
            items: components["schemas"]["OperationView"][];
        };
        /** OperationView */
        OperationView: {
            /**
             * Action
             * @enum {string}
             */
            action: "files.list_authorized" | "files.read" | "email.draft" | "email.send" | "tasks.list";
            /** Approval Ref */
            approval_ref: string | null;
            /** Approval State */
            approval_state: ("PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "REVOKED") | null;
            /** Attempt Ref */
            attempt_ref: string | null;
            /** Audit Event Ref */
            audit_event_ref: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Decision
             * @enum {string}
             */
            decision: "ALLOW" | "DENY" | "APPROVAL_REQUIRED";
            /**
             * Execution Status
             * @enum {string}
             */
            execution_status: "NOT_EXECUTED" | "SUCCEEDED" | "FAILED" | "UNKNOWN";
            /** Operation Ref */
            operation_ref: string;
            provenance: components["schemas"]["Provenance"];
            /**
             * Reason Code
             * @enum {string}
             */
            reason_code: "EXECUTION_NOT_STARTED" | "EXECUTION_SUCCEEDED" | "TOOL_FAILED_NO_EFFECT" | "APPROVAL_UNAVAILABLE" | "AUTH_INVALID" | "TASK_SCOPE_MISMATCH" | "ACTION_DISABLED" | "TASK_NOT_ACTIVE" | "PURPOSE_MISMATCH" | "RESOURCE_NOT_AUTHORIZED" | "RESOURCE_VERSION_CHANGED" | "RECIPIENT_NOT_AUTHORIZED" | "CONSENT_AMBIGUOUS" | "CONSENT_EXPIRED" | "CONSENT_REVOKED" | "EXECUTION_UNCONFIRMED" | "CONSENT_REVIEW_REQUIRED" | "APPROVAL_REJECTED" | "APPROVAL_EXPIRED" | "APPROVAL_REVOKED" | "EMAIL_CONTENT_NOT_AUTHORIZED" | "SEND_SLOT_CLAIMED" | "SEND_RECONCILIATION_REQUIRED";
            /** Reconciliation Required */
            reconciliation_required: boolean;
            /** Request Id */
            request_id: string;
            /** Revision */
            revision: number;
            /**
             * State
             * @enum {string}
             */
            state: "ADMITTED" | "PENDING_APPROVAL" | "READY" | "DENIED" | "DISPATCHING" | "SUCCEEDED" | "FAILED" | "UNKNOWN";
            /** Task Ref */
            task_ref: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
        };
        /** OwnerDisplay */
        OwnerDisplay: {
            /**
             * Display Name
             * @default Local demo owner
             * @constant
             */
            display_name: "Local demo owner";
        };
        /** OwnerSession */
        OwnerSession: {
            /**
             * Absolute Expires At
             * Format: date-time
             */
            absolute_expires_at: string;
            /**
             * Authenticated
             * @default true
             * @constant
             */
            authenticated: true;
            /** Csrf Token */
            csrf_token: string;
            /**
             * Idle Expires At
             * Format: date-time
             */
            idle_expires_at: string;
            /**
             * Mode
             * @default LOCAL_DEMO
             * @constant
             */
            mode: "LOCAL_DEMO";
            owner: components["schemas"]["OwnerDisplay"];
        };
        /** PlanningStart */
        PlanningStart: {
            /** User Request */
            user_request: string;
        };
        /** PlanningView */
        PlanningView: {
            /** Approval Ref */
            approval_ref: string | null;
            /** Authorization Decision */
            authorization_decision: ("ALLOW" | "DENY" | "APPROVAL_REQUIRED") | null;
            /** Error Code */
            error_code: ("PLANNING_FAILED" | "PLAN_OUT_OF_SCOPE" | "AUTHORIZATION_UNAVAILABLE" | "CHECKPOINT_UNAVAILABLE" | "HOST_UNAVAILABLE" | "COMMAND_TIMEOUT" | "COMMAND_UNCERTAIN") | null;
            /** Finished At */
            finished_at: string | null;
            /** Intent */
            intent: ("summarize_document" | "prepare_email" | "summarize_and_prepare_email" | "morning_brief" | "answer_question") | ("clarify_request" | "unsupported_operation") | null;
            /** Operation Ref */
            operation_ref: string | null;
            /** Outcome */
            outcome: ("PLAN_READY" | "CLARIFICATION_REQUIRED" | "UNSUPPORTED_OPERATION" | "FAILED") | null;
            /** Planning Ref */
            planning_ref: string | null;
            /**
             * Proposed Actions
             * @default []
             */
            proposed_actions: ("files.list_authorized" | "files.read" | "email.draft" | "email.send" | "tasks.list")[];
            provenance: components["schemas"]["Provenance"];
            /** Reason Code */
            reason_code: ("EXECUTION_NOT_STARTED" | "EXECUTION_SUCCEEDED" | "TOOL_FAILED_NO_EFFECT" | "APPROVAL_UNAVAILABLE" | "AUTH_INVALID" | "TASK_SCOPE_MISMATCH" | "ACTION_DISABLED" | "TASK_NOT_ACTIVE" | "PURPOSE_MISMATCH" | "RESOURCE_NOT_AUTHORIZED" | "RESOURCE_VERSION_CHANGED" | "RECIPIENT_NOT_AUTHORIZED" | "CONSENT_AMBIGUOUS" | "CONSENT_EXPIRED" | "CONSENT_REVOKED" | "EXECUTION_UNCONFIRMED" | "CONSENT_REVIEW_REQUIRED" | "APPROVAL_REJECTED" | "APPROVAL_EXPIRED" | "APPROVAL_REVOKED" | "EMAIL_CONTENT_NOT_AUTHORIZED" | "SEND_SLOT_CLAIMED" | "SEND_RECONCILIATION_REQUIRED") | null;
            /** Request Id */
            request_id: string | null;
            /** Started At */
            started_at: string | null;
            /**
             * State
             * @default NOT_STARTED
             * @enum {string}
             */
            state: "NOT_STARTED" | "RUNNING" | "FINISHED" | "FAILED" | "UNCERTAIN";
            /** Task Ref */
            task_ref: string;
        };
        /** Provenance */
        Provenance: {
            /**
             * Effect
             * @default NONE
             * @enum {string}
             */
            effect: "NONE" | "SIMULATED" | "NO_MESSAGE_SUBMISSION" | "FAKE_SMTP_ONLY" | "UNCONFIRMED";
            /**
             * Environment
             * @default OFFLINE_DEMO
             * @constant
             */
            environment: "OFFLINE_DEMO";
            /**
             * Evidence
             * @default CONFIGURED
             * @enum {string}
             */
            evidence: "CONFIGURED" | "OBSERVED" | "UNATTESTED";
            /** Execution Mode */
            execution_mode: ("SIMULATED" | "EMAIL_DRAFT" | "MAILPIT_SEND") | null;
            /**
             * Planning Source
             * @default NOT_RUN
             * @enum {string}
             */
            planning_source: "NOT_RUN" | "MOCK_MODEL" | "UNATTESTED";
        };
        /** ResourceVersion */
        ResourceVersion: {
            /**
             * Classification
             * @enum {string}
             */
            classification: "PRIVATE_ORIGINAL" | "SHAREABLE";
            /** Resource Id */
            resource_id: string;
            /** Version Ref */
            version_ref: string;
        };
        /** SessionSuccess */
        SessionSuccess: {
            /**
             * Api Version
             * @default ghost-app-v1
             * @constant
             */
            api_version: "ghost-app-v1";
            /** Data */
            data: components["schemas"]["AnonymousSession"] | components["schemas"]["OwnerSession"];
            /**
             * Replayed
             * @default false
             * @constant
             */
            replayed: false;
        };
        /** TaskCreate */
        TaskCreate: {
            /**
             * Profile Id
             * @enum {string}
             */
            profile_id: "document_simulation_v1" | "email_draft_v1" | "email_send_v1";
            /** Resource Id */
            resource_id: string | null;
        } & unknown;
        /** TaskDetail */
        TaskDetail: {
            /**
             * Allowed Action
             * @enum {string}
             */
            allowed_action: "files.list_authorized" | "files.read" | "email.draft" | "email.send" | "tasks.list";
            /** Approval Ref */
            approval_ref: string | null;
            /**
             * Authority State
             * @enum {string}
             */
            authority_state: "OPEN" | "COMPLETED" | "CANCELLED" | "EXPIRED";
            /** Authorization Version */
            authorization_version: number;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** In Flight */
            in_flight: boolean;
            /** Operation State */
            operation_state: ("ADMITTED" | "PENDING_APPROVAL" | "READY" | "DENIED" | "DISPATCHING" | "SUCCEEDED" | "FAILED" | "UNKNOWN") | null;
            /**
             * Planning State
             * @enum {string}
             */
            planning_state: "NOT_STARTED" | "RUNNING" | "FINISHED" | "FAILED" | "UNCERTAIN";
            /**
             * Profile Id
             * @enum {string}
             */
            profile_id: "document_simulation_v1" | "email_draft_v1" | "email_send_v1";
            provenance: components["schemas"]["Provenance"];
            /**
             * Purpose
             * @enum {string}
             */
            purpose: "summarize_document" | "prepare_email" | "summarize_and_prepare_email" | "morning_brief" | "answer_question";
            /** Reconciliation Required */
            reconciliation_required: boolean;
            /** Resource Ids */
            resource_ids: string[];
            /** Task Ref */
            task_ref: string;
            /** Workflow Phase */
            workflow_phase: ("PREPARING" | "PAUSED" | "ADMITTED" | "RESUMING" | "RESUMED" | "DENIED") | null;
        };
        /** TaskPage */
        TaskPage: {
            /** Items */
            items: components["schemas"]["TaskSummary"][];
            /** Next Cursor */
            next_cursor: string | null;
            /**
             * Snapshot At
             * Format: date-time
             */
            snapshot_at: string;
        };
        /** TaskSummary */
        TaskSummary: {
            /** Approval Ref */
            approval_ref: string | null;
            /**
             * Authority State
             * @enum {string}
             */
            authority_state: "OPEN" | "COMPLETED" | "CANCELLED" | "EXPIRED";
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /** Operation State */
            operation_state: ("ADMITTED" | "PENDING_APPROVAL" | "READY" | "DENIED" | "DISPATCHING" | "SUCCEEDED" | "FAILED" | "UNKNOWN") | null;
            /**
             * Planning State
             * @enum {string}
             */
            planning_state: "NOT_STARTED" | "RUNNING" | "FINISHED" | "FAILED" | "UNCERTAIN";
            /**
             * Profile Id
             * @enum {string}
             */
            profile_id: "document_simulation_v1" | "email_draft_v1" | "email_send_v1";
            provenance: components["schemas"]["Provenance"];
            /** Task Ref */
            task_ref: string;
            /** Workflow Phase */
            workflow_phase: ("PREPARING" | "PAUSED" | "ADMITTED" | "RESUMING" | "RESUMED" | "DENIED") | null;
        };
        /** TimelineItem */
        TimelineItem: {
            /** Approval Ref */
            approval_ref: string | null;
            /** Attempt Ref */
            attempt_ref: string | null;
            /** Decision */
            decision: ("ALLOW" | "DENY" | "APPROVAL_REQUIRED") | null;
            /** Event Ref */
            event_ref: string;
            /** Execution Status */
            execution_status: ("NOT_EXECUTED" | "SUCCEEDED" | "FAILED" | "UNKNOWN") | null;
            /**
             * Kind
             * @enum {string}
             */
            kind: "AUTHORIZATION" | "APPROVAL_TRANSITION" | "APPROVAL_VIEWED" | "WORKFLOW_TRANSITION" | "EXECUTION_ADMISSION" | "EXECUTION_OUTCOME";
            /** Operation Ref */
            operation_ref: string | null;
            /** Reason Code */
            reason_code: ("EXECUTION_NOT_STARTED" | "EXECUTION_SUCCEEDED" | "TOOL_FAILED_NO_EFFECT" | "APPROVAL_UNAVAILABLE" | "AUTH_INVALID" | "TASK_SCOPE_MISMATCH" | "ACTION_DISABLED" | "TASK_NOT_ACTIVE" | "PURPOSE_MISMATCH" | "RESOURCE_NOT_AUTHORIZED" | "RESOURCE_VERSION_CHANGED" | "RECIPIENT_NOT_AUTHORIZED" | "CONSENT_AMBIGUOUS" | "CONSENT_EXPIRED" | "CONSENT_REVOKED" | "EXECUTION_UNCONFIRMED" | "CONSENT_REVIEW_REQUIRED" | "APPROVAL_REJECTED" | "APPROVAL_EXPIRED" | "APPROVAL_REVOKED" | "EMAIL_CONTENT_NOT_AUTHORIZED" | "SEND_SLOT_CLAIMED" | "SEND_RECONCILIATION_REQUIRED") | null;
            /** State */
            state: ("PENDING" | "APPROVED" | "REJECTED" | "EXPIRED" | "REVOKED") | ("PREPARING" | "PAUSED" | "ADMITTED" | "RESUMING" | "RESUMED" | "DENIED") | ("ADMITTED" | "PENDING_APPROVAL" | "READY" | "DENIED" | "DISPATCHING" | "SUCCEEDED" | "FAILED" | "UNKNOWN") | null;
            /** Task Ref */
            task_ref: string;
            /**
             * Timestamp
             * Format: date-time
             */
            timestamp: string;
        };
        /** WorkflowView */
        WorkflowView: {
            /** Approval Ref */
            approval_ref: string | null;
            /** Authorization Version */
            authorization_version: number;
            /** Binding Ref */
            binding_ref: string | null;
            /** Continuation Available */
            continuation_available: boolean;
            /** Expires At */
            expires_at: string | null;
            /** Operation Ref */
            operation_ref: string | null;
            /** Phase */
            phase: ("PREPARING" | "PAUSED" | "ADMITTED" | "RESUMING" | "RESUMED" | "DENIED") | null;
            provenance: components["schemas"]["Provenance"];
            /** Reconciliation Required */
            reconciliation_required: boolean;
            /** Task Ref */
            task_ref: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    approvals_api_app_v1_approvals_get: {
        parameters: {
            query: {
                task_ref: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_ApprovalList_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    approval_detail_api_app_v1_approvals__approval_ref__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                approval_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_ApprovalDetail_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    decision_api_app_v1_approvals__approval_ref__decision_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path: {
                approval_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ApprovalDecision"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_ApprovalMutation_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    revoke_api_app_v1_approvals__approval_ref__revoke_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path: {
                approval_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IdentityModel"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_ApprovalMutation_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    documents_api_app_v1_documents_get: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_AppPage_DocumentMetadata__"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    session_status_api_app_v1_session_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description HttpOnly; SameSite=Strict; Path=/; HTTPS Secure */
                    "Set-Cookie"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSuccess"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    login_api_app_v1_session_login_post: {
        parameters: {
            query?: never;
            header: {
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    /** @description HttpOnly; SameSite=Strict; Path=/; HTTPS Secure */
                    "Set-Cookie"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionSuccess"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    logout_api_app_v1_session_logout_post: {
        parameters: {
            query?: never;
            header: {
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IdentityModel"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    /** @description HttpOnly; SameSite=Strict; Path=/; HTTPS Secure */
                    "Set-Cookie"?: string;
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    listing_api_app_v1_tasks_get: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_TaskPage_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    create_api_app_v1_tasks_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["TaskCreate"];
            };
        };
        responses: {
            /** @description Idempotent replay; current task */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_TaskDetail_"];
                };
            };
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_TaskDetail_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    detail_api_app_v1_tasks__task_ref__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_TaskDetail_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    cancel_api_app_v1_tasks__task_ref__cancel_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IdentityModel"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_CancelResult_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    operations_api_app_v1_tasks__task_ref__operations_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_OperationList_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    operation_api_app_v1_tasks__task_ref__operations__operation_ref__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_ref: string;
                operation_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_OperationView_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    planning_status_api_app_v1_tasks__task_ref__planning_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_PlanningView_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    planning_api_app_v1_tasks__task_ref__planning_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlanningStart"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_PlanningView_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    timeline_api_app_v1_tasks__task_ref__timeline_get: {
        parameters: {
            query?: {
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_AppPage_TimelineItem__"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    workflow_api_app_v1_tasks__task_ref__workflow_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_WorkflowView_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    continuation_api_app_v1_tasks__task_ref__workflow_continue_post: {
        parameters: {
            query?: never;
            header: {
                "Idempotency-Key": string;
                /** @description Exact configured origin; no forwarded-header trust. */
                Origin: string;
            };
            path: {
                task_ref: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["IdentityModel"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppSuccess_WorkflowView_"];
                };
            };
            /** @description Bad Request */
            400: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unauthorized */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Forbidden */
            403: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Not Found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Conflict */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Content Too Large */
            413: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unsupported Media Type */
            415: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Unprocessable Content */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Too Many Requests */
            429: {
                headers: {
                    /** @description Delay in seconds */
                    "Retry-After"?: string;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Internal Server Error */
            500: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Service Unavailable */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
            /** @description Gateway Timeout */
            504: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppFailure"];
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
}
