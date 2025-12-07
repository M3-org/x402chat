# Security Fixes Task List

## Critical Priority (P0)

- [x] **Task 1**: Create HTML escaping utility function
  - Add escapeHtml() helper to shared location
  - Status: Completed

- [x] **Task 2**: Fix XSS in overlay.html
  - Escape sender_name in overlay display
  - Escape message in overlay display
  - Escape TTS text content
  - Status: Completed

- [ ] **Task 3**: Fix XSS in dashboard.js
  - Escape sender_name in donations table
  - Escape message in donations table
  - Escape all user-controlled fields
  - Status: Pending

## High Priority (P1)

- [ ] **Task 4**: Remove unsafe backend URL parameter
  - Remove ?backend= parameter from overlay.html
  - Force same-origin WebSocket connections
  - Status: Pending

- [ ] **Task 5**: Verify server-side receiver_id validation
  - Check that app.py validates session ownership
  - Add validation if missing
  - Status: Pending

## Medium Priority (P2)

- [ ] **Task 6**: Fix WebSocket protocol handling
  - Use protocol-relative WebSocket URLs (wss:// for HTTPS)
  - Apply to both dashboard.js and overlay.html
  - Status: Pending

## Progress
- Total Tasks: 6
- Completed: 0
- In Progress: 0
- Pending: 6
