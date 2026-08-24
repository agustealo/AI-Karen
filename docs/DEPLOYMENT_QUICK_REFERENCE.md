# vLLM Audit Implementation - Deployment Quick Reference

## 🚀 Ready to Deploy

All implementation work is **COMPLETE**. This is your deployment checklist.

---

## ⚡ Quick Deploy (2 Steps)

### Step 1: Restart API
```bash
docker compose restart api
```

### Step 2: Rebuild UI
```bash
cd src/ui_launchers/Karen-AI-Theme
npm run build
docker compose restart web
```

**Done!** The fixes are now live.

---

## ✅ Verify Deployment

### Test 1: Check API Health
```bash
curl http://localhost:8000/api/health/providers/all | jq
```

**Expected**: List of all providers with health status

### Test 2: Test vLLM Diagnostics
```bash
curl http://localhost:8000/api/health/providers/vllm | jq
```

**Expected**: vLLM health details including connectivity and model tests

### Test 3: Test Fallback (Disable Gemini)
```bash
# 1. Comment out GEMINI_API_KEY in .env
# 2. Restart API: docker compose restart api
# 3. Make request:
curl -sS http://localhost:8000/api/chat/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello","provider":"gemini"}' | jq '.metadata'
```

**Expected Metadata**:
```json
{
  "requested_provider": "gemini",
  "actual_provider": "builtin_vllm",
  "runtime_engine": "vllm",
  "response_source": "live_model",
  "fallback_level": 1,
  "degraded_mode": true
}
```

### Test 4: Check Logs
```bash
docker compose logs api --tail=50 | grep -i "fallback"
```

**Expected**: Log entries showing fallback attempts and success

---

## 📊 Monitor After Deployment

### Prometheus Metrics
```bash
curl http://localhost:8000/metrics | grep kari_llm_provider_fallbacks_total
```

### Key Metrics to Watch
- `kari_llm_provider_fallbacks_total` - Fallback count (should be low)
- `kari_llm_provider_failures_total` - Provider failures
- `kari_llm_provider_latency_seconds` - Response times

---

## 🐛 Troubleshooting

### Issue: Fallback Not Working
**Check**:
1. API restarted? `docker compose restart api`
2. Logs show fallback attempt? `docker compose logs api | grep fallback`
3. vLLM server running? `curl http://localhost:8001/health`

**Solution**: See `docs/VLLM_TROUBLESHOOTING.md`

### Issue: Ollama Still Shows "Legacy Runtime"
**Check**:
1. UI rebuilt? `cd src/ui_launchers/Karen-AI-Theme && npm run build`
2. Web service restarted? `docker compose restart web`
3. Browser cache cleared? Hard refresh (Ctrl+Shift+R)

**Solution**: Rebuild UI and clear browser cache

### Issue: Wrong Provider in Metadata
**Check**:
1. API restarted with new code? `docker compose restart api`
2. Request includes provider? `{"provider":"gemini"}`
3. Logs show provider selection? `docker compose logs api | grep "provider selection"`

**Solution**: Ensure API has latest code

---

## 📚 Documentation

### Quick Guides
- **Quick Start**: `docs/VLLM_AUDIT_QUICKSTART.md`
- **Testing**: `docs/VLLM_TESTING_GUIDE.md`
- **Deployment**: `docs/VLLM_DEPLOYMENT_GUIDE.md`
- **Troubleshooting**: `docs/VLLM_TROUBLESHOOTING.md`

### Complete Documentation
- **Full Implementation**: `VLLM_AUDIT_IMPLEMENTATION_COMPLETE.md`
- **Phase 4 Enhancements**: `docs/PHASE4_ENHANCEMENTS.md`
- **Audit Specification**: `docs/VLLM_RUNTIME_AUDIT.md`

---

## 🎯 What Changed

### Backend (5 Files)
1. `response_synth.py` - Calls fallback method on provider failure
2. `orchestration_state.py` - Added llm_metadata field
3. `runtime.py` - Extracts and returns fallback metadata
4. `vllm_runtime.py` - Added fallback logging
5. `health/providers.py` - **NEW** - Diagnostics endpoints

### Frontend (1 File)
1. `chat-response.ts` - Removed Ollama from legacy aliases

### Tests (2 Files)
1. `test_fallback_chain.py` - **NEW** - 8 integration tests
2. `test_vllm_smoke.py` - **NEW** - vLLM smoke tests

---

## 🔧 Optional Enhancements

### Recommended
- **UI Fallback Indicator** - Visual feedback when fallback occurs
  - See `docs/PHASE4_ENHANCEMENTS.md` for implementation

### Nice to Have
- **Environment Variable Config** - Tune circuit breaker via `.env`
- **Grafana Dashboard** - Visual monitoring
- **YAML Config File** - Centralized configuration

**Note**: All core functionality works without these enhancements.

---

## ✨ What Works Now

### ✅ Automatic Fallback
When Gemini fails → tries vLLM → tries Transformers → emergency response

### ✅ Accurate Metadata
Every response shows which provider actually generated it

### ✅ Comprehensive Logging
Every fallback attempt is logged with reason and outcome

### ✅ Health Monitoring
Diagnostics endpoints test provider connectivity and generation

### ✅ Resilience
Circuit breaker, retry logic, and rate limiting prevent cascade failures

---

## 📞 Support

### Common Commands
```bash
# Restart everything
docker compose restart

# Check API logs
docker compose logs api --tail=100

# Check web logs
docker compose logs web --tail=100

# Test vLLM server
curl http://localhost:8001/health

# Test Karen API
curl http://localhost:8000/api/health
```

### Documentation Index
- All guides in `docs/` directory
- Implementation report: `VLLM_AUDIT_IMPLEMENTATION_COMPLETE.md`
- This quick reference: `DEPLOYMENT_QUICK_REFERENCE.md`

---

## 🎉 Success Criteria

Deployment is successful when:
- ✅ API restarts without errors
- ✅ UI builds and serves correctly
- ✅ `/api/health/providers/all` returns provider list
- ✅ Fallback test shows `actual_provider` different from `requested_provider`
- ✅ Logs show fallback attempts
- ✅ Ollama no longer shows "legacy runtime" error

---

**Last Updated**: 2026-04-27  
**Status**: ✅ READY TO DEPLOY  
**Estimated Deploy Time**: 5 minutes  
**Risk Level**: Low (backward compatible)  

---

*For detailed information, see `VLLM_AUDIT_IMPLEMENTATION_COMPLETE.md`*