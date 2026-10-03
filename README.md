# Second Serving — OpenAI Hackathon 2026, Team 3

Second Serving is a local surplus-food marketplace built by Team 3. Kitchens describe end-of-shift food in natural language or by voice, review AI-created listing drafts, and publish them. Recipients browse nearby food, reserve exact quantities, and explore practical recipes that combine expiring ingredients without creating an unreasonable pickup route.

> Restaurants have food left over. People and community kitchens need it. Second Serving connects them before the food goes to waste.

## Product flows

### Kitchens and food donors

1. Create an email-verified kitchen account.
2. Speak or type a shift note such as “12 chicken-and-rice boxes and 8 pounds of carrots, pickup 9–9:45.”
3. Let the guarded extraction agent turn it into structured donation drafts.
4. Review quantities, pickup timing, allergens, and any uncertain fields.
5. Publish only after explicit human confirmation.

### Recipients and community kitchens

1. Browse available meals and ingredients without creating an account.
2. Sign in when ready to reserve.
3. Choose a quantity and receive the exact pickup address and pickup code.
4. Generate ingredient plans from their current location or a ZIP code, constrained by maximum stops and route distance.
5. Reserve every ingredient in a selected plan with one all-or-nothing transaction.

### End-to-end test flow

The development environment starts without seeded food or manufactured activity. To test the complete live flow:

1. Create and verify a kitchen account.
2. Speak or type an end-of-shift note, review the AI-created drafts, and publish a listing.
3. Create and verify a separate recipient account.
4. Reserve part of the listing and confirm its available quantity decreases atomically.
5. Verify the exact pickup location is disclosed only after the reservation succeeds.

## Stack

- Next.js static export hosted by AWS Amplify Hosting
- Amazon Cognito User Pools for email/password signup and email verification codes
- API Gateway HTTP API with a Cognito JWT authorizer
- Python 3.12 Lambda API
- DynamoDB on-demand tables for users, organizations, memberships, listings, reservations, and short-lived agent drafts
- Amazon Location Places for server-side ZIP and donor-address geocoding
- Private S3 bucket with presigned uploads for photos and temporary voice clips
- OpenAI through LangChain Deep Agents, with LangSmith tracing; both API keys live in AWS Secrets Manager
- AWS SAM/CloudFormation for repeatable infrastructure

```text
Browser
  ├── static app ───────────────> AWS Amplify Hosting
  ├── signup/sign-in ───────────> Amazon Cognito
  └── HTTPS + Cognito JWT ──────> API Gateway
                                      │
                                      ▼
                                  AWS Lambda
                              ┌───────┼────────┐
                              ▼       ▼        ▼
                          DynamoDB    S3   Secrets Manager
                                              │
                                              ▼
                                      OpenAI + Deep Agents
```

## Roles and authorization

| Role | Capabilities |
| --- | --- |
| Visitor | Browse public listings; exact pickup locations are omitted. |
| Recipient | Reserve inventory and view their own reservations and pickup details. |
| Kitchen owner/manager/staff | Create listings and use AI extraction for their verified organization. |

Cognito authenticates users, while organization membership and roles live in DynamoDB. The API never trusts an organization ID merely because it arrived in a request: donor mutations verify the authenticated user’s membership first.

## AI safety boundary

The model has no raw database or AWS tool. Its tools are narrow, request-scoped application functions, and user/organization identity is injected from the verified JWT context rather than chosen by the model.

- The extraction agent can read the current organization and its recent donations, then save a review-only draft. It cannot publish.
- The recipe agent can inspect available food and estimate a route. It cannot reserve inventory.
- Filesystem, shell, todo, and subagent tools supplied by Deep Agents are excluded.
- A deny-all filesystem permission is also applied at runtime.
- Route constraints are recomputed by application code after model output; plans outside the stop or mileage limit are discarded.
- Allergens, quantities, storage rules, and pickup times are never supposed to be invented. Missing values are flagged for review.

The OpenAI and LangSmith keys are fetched by Lambda from Secrets Manager and are never compiled into the frontend or committed to Git. Agent runs are traced to the environment-specific LangSmith project `second-serving-<environment>` and labeled by agent type.

## Live development environment

- App: https://main.d3tdgkgyxb5md7.amplifyapp.com
- API: https://1h502bm01h.execute-api.us-east-1.amazonaws.com/dev
- CloudFormation stack: `second-serving-dev` in `us-east-1`

The development database is intentionally unseeded. Listings, reservations, and visible availability should come only from accounts actively testing the application. Exact pickup locations are omitted from public responses and returned only after a successful reservation.

## Data model

| Table | Purpose |
| --- | --- |
| Users | App profile linked to the Cognito subject. |
| Organizations | Kitchens/food donors, pickup address, and approximate route coordinates. |
| Memberships | User-to-organization role mapping with a user lookup index. |
| Listings | Available quantity, food type, allergens, pickup window, and donor metadata. |
| Reservations | Recipient, quantity, pickup code, and reservation status. |
| AgentRuns | Short-lived AI drafts and audit context, removed automatically after 14 days. |

Reservations use one DynamoDB transaction: a conditional inventory decrement and reservation insert either both succeed or both fail. This prevents two recipients from claiming the same final quantity.

Meal-plan bundles use the same pattern across every selected listing. All inventory decrements and reservation records commit in one DynamoDB transaction, so a recipient receives the complete ingredient bundle or nothing is reserved.

The transaction path uses DynamoDB's low-level client and explicit `AttributeValue` serialization. Resource-style clients must not be substituted there because doing so would serialize transaction keys twice.

### South End demo data

Seed the deployed development stack with six deterministic kitchen profiles and 30 published ingredient listings for South End Charlotte:

```bash
PYTHONPATH=backend python3 backend/seed_demo.py --dry-run
PYTHONPATH=backend python3 backend/seed_demo.py
```

The seed includes Club West Brewing, Chapter 6, Tremont Kitchen + Bar, Superica, Hawkers Asian Street Food, and Barcelona Wine Bar. Rerunning it refreshes quantities and pickup windows without duplicating records. It only upserts records carrying the deterministic `south-end-demo-v1` seed IDs; unrelated user data is not changed or deleted.

## Local frontend

```bash
npm install
cp .env.example .env.local
npm run dev
```

Without AWS values, the app renders a safe empty state for local UI work. With the public AWS values populated, Cognito, live listings, reservations, onboarding, and AI extraction are enabled.

### Public frontend configuration

| Variable | Description |
| --- | --- |
| `NEXT_PUBLIC_AWS_REGION` | Region containing Cognito and the API. |
| `NEXT_PUBLIC_COGNITO_USER_POOL_ID` | Public Cognito user-pool identifier. |
| `NEXT_PUBLIC_COGNITO_CLIENT_ID` | Public browser app-client identifier; it has no client secret. |
| `NEXT_PUBLIC_API_URL` | API Gateway stage URL. |
| `NEXT_PUBLIC_SITE_URL` | Canonical deployed URL used for social metadata. |

Do not add the OpenAI key—or any AWS access key—to a `NEXT_PUBLIC_*` variable.

## Validate

```bash
npm run lint
npm run build
npm run infra:validate
npm run infra:build
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests
npm audit --omit=dev
```

## Deploy

Use an IAM Identity Center or least-privilege administrative role—not AWS account root—then run:

```bash
sam deploy --config-file infra/samconfig.toml --guided
```

After deployment:

1. Open AWS Secrets Manager and replace the `apiKey` placeholders in `/second-serving/dev/openai` and `/second-serving/dev/langsmith`.
2. Read the stack outputs for the API URL, Cognito IDs, and Amplify app ID.
3. Set those three `NEXT_PUBLIC_*` values locally and rebuild `out/`, or connect the Amplify app to this repository and enable automatic builds.
4. Update the stack's `FrontendOrigin` and `SiteUrl` parameters to the final Amplify origin so CORS and social metadata use the deployed site.

The CloudFormation template retains DynamoDB tables, the media bucket, Cognito pool, and API-key secrets when the stack is deleted. That protects hackathon data but means cleanup is intentionally a separate, explicit step.

### OpenAI secret format

Set `/second-serving/dev/openai` in AWS Secrets Manager to a JSON value with this shape:

```json
{"apiKey":"YOUR_OPENAI_API_KEY"}
```

Never commit the actual value. Lambda reads the secret at request time, so changing it does not require another frontend build.

### LangSmith tracing

Set `/second-serving/dev/langsmith` in AWS Secrets Manager to a JSON value with this shape:

```json
{"apiKey":"YOUR_LANGSMITH_API_KEY"}
```

The Lambda enables LangSmith tracing automatically and sends both agents to the `second-serving-dev` project. Donation extraction and recipe planning runs have distinct names, tags, and `agent_type` metadata so they can be filtered in LangSmith. For local backend development, set `LANGSMITH_API_KEY` directly; tracing and the `second-serving-local` project name are then enabled automatically.

Traces include model and tool inputs and outputs. Treat the LangSmith workspace as application data infrastructure and configure its access and retention accordingly.

## Main API routes

- Public: `GET /health`, `GET /listings`, `GET /listings/{listingId}`
- Account: `GET /me`, `POST /me/bootstrap`
- Recipient: `POST /reservations`, `GET /me/reservations`
- Donor: `POST /listings`, `POST /uploads`, `POST /agent/extract`
- Planning: `POST /agent/recipes` queues a recipe run using browser coordinates or a US ZIP code
- Recipe runs: `GET /agent/recipes` lists the signed-in user's recent runs; `GET /agent/recipes/{runId}` returns status and saved results
- Atomic plan reservation: `POST /reservations/bulk`

Reservations use a DynamoDB transaction with a conditional inventory decrement, so two recipients cannot successfully reserve the same final quantity.

## Privacy and security notes

- Exact pickup addresses and coordinates are stripped from public listing responses.
- Recipient browser coordinates and ZIP geocoding results are carried in the encrypted, short-lived recipe-job queue and are not saved with recipe results.
- Pickup details are returned only after a successful authenticated reservation.
- Uploads use five-minute presigned S3 URLs and an allowlist of image/audio content types.
- Temporary voice objects expire from S3 after one day.
- DynamoDB uses encryption at rest and point-in-time recovery.
- Data resources and the Cognito pool use retain policies to prevent accidental stack deletion from destroying hackathon data.
- API CORS is restricted to the deployed Amplify origin.

## MVP limitations and next steps

- Cognito’s default email sender is suitable for a hackathon but should be replaced with a production SES configuration.
- The current route estimate uses straight-line legs with a conservative road-distance multiplier; a production version should use a real routing provider.
- Donation review supports confirmation, but field-by-field editing should be completed before a public launch.
- Add reservation cancellation/expiration, pickup completion, organization invitations, moderation, and operational dashboards.
- Move donation extraction to the background-job pattern if it regularly approaches API Gateway’s request timeout.
