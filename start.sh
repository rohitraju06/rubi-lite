#!/bin/bash
cd /app/rubi-lite
npm run dev -- --hos
gunicorn -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000