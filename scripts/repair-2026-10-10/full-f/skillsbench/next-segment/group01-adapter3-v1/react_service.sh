#!/bin/bash
# Original test.sh execution setup split into a candidate-only service actor.
# No verifier, tests, oracle, model credentials, or host mounts enter this actor.
set +e
cd /services/api-simulator
npm start >/run/api.log 2>&1 &
for i in {1..15}; do
  if curl -sf http://localhost:3001/health >/dev/null; then break; fi
  sleep 1
done
cd /app
npm run build >/run/build.log 2>&1
npm start >/run/app.log 2>&1 &
for i in {1..30}; do
  if curl -s http://localhost:3000 >/dev/null; then touch /run/objrun-react-ready; break; fi
  sleep 1
done
exit 0
