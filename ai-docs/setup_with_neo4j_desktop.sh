#!/bin/bash
# Setup Potpie with Neo4j Desktop + Minimal Docker

set -e

echo "🚀 Setting up Potpie with Neo4j Desktop + Minimal Docker"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found. Creating from template...${NC}"
    cp .env.template .env
    echo -e "${GREEN}✅ Created .env file${NC}"
    echo -e "${YELLOW}⚠️  Please edit .env and add your NEO4J_PASSWORD and OPENAI_API_KEY${NC}"
    echo ""
    read -p "Press enter after updating .env file..."
fi

# Check Neo4j Desktop
echo -e "${YELLOW}📊 Neo4j Desktop Setup${NC}"
echo "Please ensure:"
echo "  1. Neo4j Desktop is installed"
echo "  2. A database is created and started"
echo "  3. APOC plugin is installed"
echo "  4. You've noted the password"
echo ""
read -p "Press enter when Neo4j Desktop is ready..."

# Test Neo4j connection
echo ""
echo -e "${YELLOW}🔍 Testing Neo4j connection...${NC}"
source .venv/bin/activate 2>/dev/null || true

python3 << PYEOF
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
user = os.getenv('NEO4J_USERNAME', 'neo4j')
pwd = os.getenv('NEO4J_PASSWORD')

if not pwd:
    print('❌ NEO4J_PASSWORD not set in .env file!')
    exit(1)

try:
    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    driver.verify_connectivity()
    driver.close()
    print('✅ Neo4j connected successfully!')
except Exception as e:
    print(f'❌ Neo4j connection failed: {e}')
    print('   Please check:')
    print('   - Neo4j Desktop database is running')
    print('   - Password in .env matches Neo4j Desktop')
    print('   - URI is correct (check port in Desktop)')
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo -e "${RED}Neo4j connection failed. Please fix and try again.${NC}"
    exit 1
fi

# Start minimal Docker services
echo ""
echo -e "${YELLOW}📦 Starting PostgreSQL and Redis...${NC}"
docker-compose -f docker-compose.minimal.yaml up -d

# Wait for PostgreSQL
echo -e "${YELLOW}⏳ Waiting for PostgreSQL to be ready...${NC}"
sleep 5

# Check PostgreSQL
docker exec potpie_postgres pg_isready -U postgres > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ PostgreSQL is ready${NC}"
else
    echo -e "${RED}❌ PostgreSQL failed to start${NC}"
    exit 1
fi

# Run migrations
echo ""
echo -e "${YELLOW}🔧 Running database migrations...${NC}"
source .venv/bin/activate
alembic upgrade head

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Migrations completed${NC}"
else
    echo -e "${RED}❌ Migrations failed${NC}"
    exit 1
fi

# Summary
echo ""
echo -e "${GREEN}🎉 Setup complete!${NC}"
echo ""
echo "Services running:"
echo "  ✅ Neo4j Desktop (bolt://localhost:7687)"
echo "  ✅ PostgreSQL (localhost:5432)"
echo "  ✅ Redis (localhost:6379)"
echo ""
echo "Next steps:"
echo "  📋 CLI usage:     python ./potpie_cli.py projects"
echo "  🚀 Start backend: ./start.sh"
echo "  💻 Start UI:      cd potpie-ui && pnpm dev"
echo ""
echo "Useful commands:"
echo "  docker-compose -f docker-compose.minimal.yaml ps     # Check status"
echo "  docker-compose -f docker-compose.minimal.yaml logs   # View logs"
echo "  docker-compose -f docker-compose.minimal.yaml down   # Stop services"
