# Emergency Rollback Procedure

**Last Updated:** December 4, 2024
**Purpose:** Quick recovery if security fixes cause issues

---

## When to Rollback

Rollback immediately if you observe:
- ❌ Dashboard fails to load
- ❌ Overlay shows console errors
- ❌ Donations cannot be submitted
- ❌ TTS stops working
- ❌ WebSocket connection failures
- ❌ Any critical functionality broken

---

## Pre-Deployment (Create Rollback Point)

Before deploying security fixes, create a git tag:

```bash
git tag -a v1.0-pre-security-fix -m "Last stable before XSS fixes"
git push origin v1.0-pre-security-fix
```

---

## Rollback Steps

### Option 1: Quick Rollback (VPS)

```bash
# SSH to VPS
ssh user@x402chat.com

# Navigate to app directory
cd /home/pump/x402chat

# Checkout previous stable version
git fetch origin
git checkout v1.0-pre-security-fix

# Restart service
sudo systemctl restart x402chat

# Watch logs for startup
journalctl -u x402chat -f
```

### Option 2: Rollback via Local Machine

```bash
# On your local machine
git checkout v1.0-pre-security-fix
git push origin main --force  # Use with caution!

# Then on VPS
ssh user@x402chat.com
cd /home/pump/x402chat
git pull origin main
sudo systemctl restart x402chat
```

---

## Verification After Rollback

1. **Check service status:**
   ```bash
   sudo systemctl status x402chat
   ```

2. **View recent logs:**
   ```bash
   journalctl -u x402chat --since "5 minutes ago"
   ```

3. **Test critical paths:**
   - Open https://x402chat.com/dashboard
   - Submit a test donation
   - Check overlay in browser
   - Verify WebSocket connection (check console)

---

## Common Issues & Quick Fixes

### Issue: "Module not found" errors

**Cause:** Import path issues in JavaScript files

**Quick Fix:** Check browser console for specific file path, fix import to use absolute path `/security-utils.js`

### Issue: "dashboard is not defined"

**Cause:** ES module scope isolation breaking global variable

**Fix:** Ensure `window.dashboard = dashboard;` is present in dashboard.js line 1062

### Issue: Overlay TTS not working

**Cause:** escapeHtml breaking TTS text

**Fix:** Verify escaped strings are passed directly to `speak()` without decoding

### Issue: Backend WebSocket connection to wrong host

**Cause:** Protocol-relative URL not working

**Fix:** Check browser console for WebSocket connection URL - should match origin

---

## Files Modified (For Reference)

If you need to manually revert specific files:

```bash
# Revert specific file
git checkout v1.0-pre-security-fix -- static/overlay.html

# Revert multiple files
git checkout v1.0-pre-security-fix -- static/overlay.html static/dashboard.js

# Restart after manual revert
sudo systemctl restart x402chat
```

**Modified files:**
- `static/overlay.html` - Module conversion, XSS fixes, TTS fix
- `static/dashboard.html` - Module tag
- `static/dashboard.js` - Import + escaping
- `static/donate.js` - Import + escaping
- `app.py` - Sanitization + CSP headers

---

## Contact for Support

If rollback doesn't resolve the issue:
1. Check GitHub issues: https://github.com/M3-org/x402chat/issues
2. Review security audit report: `.claude/tasks/security-fixes/report.md`
3. Contact team member who deployed the fixes

---

## Prevention (Before Next Deployment)

Before deploying future updates:

1. ✅ Create git tag for rollback
2. ✅ Test on staging environment first (if available)
3. ✅ Review changes in plan file: `/home/jin/.claude/plans/jiggly-hatching-stardust.md`
4. ✅ Run manual test checklist (see plan file)
5. ✅ Have this ROLLBACK.md open during deployment
6. ✅ Monitor logs immediately after deployment

---

**Remember:** It's always safer to rollback and investigate than to leave broken functionality in production.
