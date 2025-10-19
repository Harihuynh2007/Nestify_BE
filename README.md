# Nestify_BE

> A modern, scalable task management system built with **Django + Django REST Framework + Channels**, designed for real-time collaboration, flexible permissions, and enterprise-grade architecture.

---

## 🏗️ System Architecture

| Layer | Technology | Description |
|-------|-------------|-------------|
| **Backend** | Django 5.2.3 + DRF | REST API for boards, cards, workspaces |
| **Realtime** | Django Channels + Redis | WebSocket notification system |
| **Database** | SQLite (dev) → PostgreSQL (prod) | Normalized relational schema |
| **Auth** | JWT (SimpleJWT) + Google OAuth2 | Stateless authentication |
| **WebSocket Auth** | Custom JWT middleware | Secure socket handshake |
| **Storage** | Local (dev) → AWS S3 (prod) | File and attachment storage |
| **Queue (optional)** | Celery + Redis | Background tasks / email sending |

```bash
Django (REST + WebSocket)
├── API: DRF views + serializers
├── Channels: Notifications via Redis
├── PostgreSQL: Primary DB
└── S3: Attachment storage
```

---

## 🧱 Data Model Overview (15 Models)

**Core Models**
- Workspace (multi-tenant container)
- WorkspaceMembership: user roles (`owner`, `admin`, `member`)
- Board: kanban board (visibility: `private`, `workspace`, `public`)
- BoardMembership: board access roles (`admin`, `editor`, `viewer`)
- List, Card: columns and tasks

**Card Features**
- CardMembership: `assignee` / `reviewer`
- Label, Comment, Checklist, ChecklistItem, Attachment, CardActivity

**Collaboration**
- BoardInviteLink: share board via token
- Notification: real-time activity alerts

---

## 🔐 Permission System

| Level | Roles | Permissions |
|--------|--------|-------------|
| **Workspace** | Owner / Admin / Member | Create boards based on policy |
| **Board** | Owner / Admin / Editor / Viewer | CRUD boards, lists, cards |
| **Card** | Creator / Shared members | Edit, comment, assign, attach |

**Decorators**
```python
@require_board_viewer('board_id')
@require_board_editor('board_id')
@require_card_editor('card_id')
```

---

## 🌐 REST API Summary

| Resource | Endpoint | Description |
|-----------|-----------|-------------|
| **Auth** | /api/auth/* | Register / Login / Google / Profile |
| **Workspaces** | /api/workspaces/ | CRUD + list boards |
| **Boards** | /api/workspaces/{id}/boards/ | CRUD, close/reopen, transfer owner |
| **Lists / Cards** | /api/lists/{id}/cards/ | CRUD lists, drag & drop cards |
| **Labels / Members / Watchers** | /api/boards/{id}/labels/ | Manage tags, members, followers |
| **Comments / Activity** | /api/cards/{id}/comments/ | Create comment → push notification |
| **Attachments** | /api/cards/{id}/attachments/ | Upload / rename / delete / cover |
| **Notifications** | /api/notifications/ | Realtime + REST management |
| **Search** | /api/search/users/?q= | User lookup by email/name |

---

## 🔌 Realtime Notifications (WebSocket)

**Endpoint:**
```
/ws/notifications/?token=<JWT>
```

**Flow:**
1. Client connects via JWT token.
2. Server joins group `user_{id}`.
3. New comment → create `Notification` → broadcast via Redis → client receives instantly.

**Client Example (JS):**
```js
const ws = new WebSocket(`wss://api.tasknest.com/ws/notifications/?token=${jwt}`);
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## 🧩 Business Logic Flows

1. Comment → Notification → WebSocket push  
2. Share board via token invite or email  
3. Drag & Drop cards (batch update, atomic transaction)  
4. Transfer ownership between users/admins  

---

## 🐛 Known Issues & Fixes

| File | Fix |
|------|-----|
| services.py | Replace `user_id` → `recipient_id` |
| consumers.py | Replace `user=self.user` → `recipient=self.user` |
| signals.py | Disable duplicate broadcast |
| settings.py | Fix `ASGI_APPLICATION = 'config.asgi.application'` |

---

## 🚀 Deployment

**Required ENV variables**
```bash
SECRET_KEY=...
DEBUG=False
ALLOWED_HOSTS=api.tasknest.com
DATABASE_URL=postgresql://user:pass@host:5432/tasknest
REDIS_URL=redis://localhost:6379/0
GOOGLE_OAUTH2_CLIENT_ID=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=tasknest-media
```

**Production stack**
```
Nginx → Daphne (ASGI) → Django
PostgreSQL + Redis
S3 media storage
Supervisor (process manager)
```

---

## 📈 Performance Optimization

- `select_related`, `prefetch_related` on all heavy queries  
- Caching: user roles, unread counts (Redis)  
- DB indexes: `(recipient, is_read, -created_at)`  
- Connection pooling (`CONN_MAX_AGE = 600`)  
- S3 storage for attachments  

---

## 🧪 Testing & Monitoring

- Unit tests for models, permissions, API, websocket  
- Load tests with Locust (`locustfile.py`)  
- Health check endpoint `/health/`  
- Logging: console + rotating file logs  
- Sentry / Silk for performance & error tracking  

---

## 🔒 Security Best Practices

- JWT rotation & refresh tokens  
- Input sanitization (`bleach`)  
- Rate limiting (`AnonRateThrottle`, `UserRateThrottle`)  
- CSRF secure cookies for web forms  
- Virus scan for uploaded files  
- Secrets via `.env` (django-environ)

---

## 🧭 Scalability Roadmap

| Phase | Target Users | Architecture |
|--------|---------------|---------------|
| 1️⃣ Single Server | 1,000 | Django + Redis + PostgreSQL |
| 2️⃣ Vertical Scaling | 3,000 | Multi-process Daphne, PgBouncer |
| 3️⃣ Horizontal Scaling | 10,000+ | Load-balanced Django, Redis Cluster |
| 4️⃣ Multi-Region | 100,000+ | Cloudflare + Multi-region RDS/Redis |

---

## 🔐 Disaster Recovery

- Daily PostgreSQL dump  
- Redis RDB persistence  
- S3 versioning for media  
- Restore steps scripted in `/docs/recovery.md`  
- Uptime & alerting (PagerDuty/Slack)

---

## 🧩 Integrations

- Celery (async email tasks)  
- SendGrid (email service)  
- Elasticsearch (advanced search)  
- AWS S3 (storage backend)

---

## 📚 Example Clients

**Python**
```python
api = TaskNestAPI('http://localhost:8000', 'user@example.com', 'password')
api.create_board(workspace_id=1, name='My Board')
```

**JavaScript**
```js
const api = new TaskNestAPI('https://api.tasknest.com');
await api.login('user@example.com', 'password');
api.connectNotifications();
```

---

## 🎯 Project Summary

✅ 15 Models • 30+ Endpoints • JWT Auth • Google Login • WebSocket Realtime  
✅ Permission Hierarchy (Workspace → Board → Card)  
✅ File Upload • Checklist • Label • Comment • Activity Log  
⚠️ To-Do: Add rate limiting, S3 setup, PostgreSQL migration, test coverage.


## 🧑‍💻 Maintainers

**Author:** Hari ([@hminhhai2000](mailto:hminhhai2000@gmail.com))  
**Tech Stack:** Django • DRF • Redis • Channels • PostgreSQL • AWS S3  
**License:** MIT
