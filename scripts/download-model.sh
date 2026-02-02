#!/bin/bash
# Download the embedding model for offline deployment
# Run this on a machine with internet access, then copy to server

set -e

MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"
OUTPUT_DIR="${1:-./model-cache}"

echo "Downloading model: $MODEL_NAME"
echo "Output directory: $OUTPUT_DIR"

mkdir -p "$OUTPUT_DIR"

python3 -c "
import os
os.environ['HF_HOME'] = '$OUTPUT_DIR'
os.environ['TRANSFORMERS_CACHE'] = '$OUTPUT_DIR'
os.environ['SENTENCE_TRANSFORMERS_HOME'] = '$OUTPUT_DIR'

from sentence_transformers import SentenceTransformer
print('Downloading model...')
model = SentenceTransformer('$MODEL_NAME')
print('Model downloaded successfully!')
print(f'Cache location: $OUTPUT_DIR')
"

echo ""
echo "Done! To deploy to your server:"
echo ""
echo "1. Copy the model cache to your server:"
echo "   scp -r $OUTPUT_DIR user@server:/path/to/job-match-backend/model-cache"
echo ""
echo "2. On the server, copy into the Docker volume:"
echo "   docker compose up -d"
echo "   docker cp model-cache/. backend-jobmatch:/home/runner/.cache/huggingface/"
echo "   docker compose restart backend"
echo ""
echo "Or mount directly in docker-compose.yml:"
echo "   volumes:"
echo "     - ./model-cache:/home/runner/.cache/huggingface"
