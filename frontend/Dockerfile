# syntax=docker/dockerfile:1.7

# ============================================================================
# Base image — Node 20 LTS slim variant (~180MB)
# ============================================================================
FROM node:20-slim AS base

# Set working directory
WORKDIR /app

# ============================================================================
# Dependency installation — copied FIRST for Docker layer caching
# Same pattern as the backend: package.json changes rarely, code changes often
# ============================================================================
COPY package.json ./

# Use npm ci if package-lock.json exists, otherwise npm install
# On first build there's no lockfile, so npm install creates one
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ============================================================================
# Application code — copied LAST
# ============================================================================
COPY . .

# ============================================================================
# Runtime configuration
# ============================================================================
EXPOSE 5173

# Healthcheck: Vite's dev server responds on port 5173
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "require('http').get('http://localhost:5173', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

# Run the Vite dev server
# In docker-compose we'll mount the code as a volume for hot-reload
CMD ["npm", "run", "dev"]