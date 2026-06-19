.PHONY: help install test lint clean build deploy docker-build docker-run

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install Python dependencies
	pip install -r requirements.txt

test: ## Run Django tests
	python manage.py test

migrate: ## Run Django migrations
	python manage.py migrate

check: ## Run Django system checks
	python manage.py check

makemigrations: ## Make Django migrations
	python manage.py makemigrations

lint: ## Run linting (if black/flake8 installed)
	-black --check .
	-flake8 .

format: ## Format code with black
	black .

clean: ## Clean up generated files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf build/ dist/ *.egg-info/

build: ## Build the project (placeholder)
	@echo "Building project..."

deploy: ## Deploy the project (placeholder)
	@echo "Deploying project..."

docker-build: ## Build Docker image
	docker-compose build

docker-run: ## Run with Docker Compose
	docker-compose up

docker-stop: ## Stop Docker Compose
	docker-compose down

flutter-get: ## Get Flutter dependencies
	cd flutter_application_plc && flutter pub get

flutter-test: ## Run Flutter tests
	cd flutter_application_plc && flutter test

flutter-build: ## Build Flutter APK
	cd flutter_application_plc && flutter build apk --debug

run-local: ## Run locally (Django + Flutter)
	@echo "Starting Django..."
	python manage.py runserver 0.0.0.0:8000 &
	@echo "Starting Flutter..."
	cd flutter_application_plc && flutter run

run-lan: ## Run for LAN (get IP)
	@echo "Getting IP..."
	@IP=$$(hostname -I | awk '{print $$1}') && echo "IP: $$IP" && python manage.py runserver $$IP:8000

# Production deployment commands
deploy: ## Deploy to production server
	@echo "Deploying to production..."
	./deploy.sh

docker-prod: ## Run production Docker stack
	docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

logs: ## View production logs
	docker-compose logs -f

backup: ## Backup database
	@echo "Creating database backup..."
	docker-compose exec db pg_dump -U plc_user plc_db > backup_$$(date +%Y%m%d_%H%M%S).sql

health: ## Check application health
	curl -f http://localhost/health/ || echo "Health check failed"

# Automated deployment commands
auto-deploy: ## Run fully automated deployment
	./auto_deploy.sh

run-single: ## Run single container locally
	./run.sh

build-single: ## Build single container image
	docker build -f Dockerfile.single -t plc-project:latest .

build-mobile: ## Build mobile apps
	./build_mobile.sh

push-docker: ## Push Docker image to registry
	docker tag plc-project:latest $(DOCKER_USERNAME)/plc-project:latest
	docker push $(DOCKER_USERNAME)/plc-project:latest

# Production deployment commands
deploy-prod: ## Deploy to production server (requires SSH access)
	@echo "Deploying to production server..."
	ssh $(PROD_HOST) "cd /opt/plc-project && git pull && ./auto_deploy.sh"

backup-prod: ## Backup production database
	@echo "Creating production backup..."
	ssh $(PROD_HOST) "docker exec plc-app pg_dump -U plc_user plc_db > /opt/plc-project/backup_$$(date +%Y%m%d_%H%M%S).sql"

logs-prod: ## View production logs
	ssh $(PROD_HOST) "docker logs -f plc-app"