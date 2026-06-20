#!/bin/bash
set -e

echo "=== OrchestrAI Startup ==="

# Backend
echo "[1/3] Installing Python dependencies..."
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -q

echo "[2/3] Starting backend on http://localhost:8000 ..."
source venv/bin/activate && python3 main.py &
BACKEND_PID=$!
cd ..

# Frontend
echo "[3/3] Installing and starting frontend on http://localhost:3000 ..."
cd frontend
npm install -q
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ OrchestrAI is running!"
echo "   Frontend: http://localhost:3000"
echo "   Backend:  http://localhost:8000"
echo "   API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'" EXIT INT
wait
