STACK_CMD := docker compose -f docker-compose.yml -f docker-compose.local-dev.yml
APP_SERVICE := web
SERVICE_EXEC := exec $(APP_SERVICE)
ARTISAN := php artisan
SERVICE_ARTISAN := $(SERVICE_EXEC) ${ARTISAN}
# Script name for tinker-execute-script target
$SCRIPT ?= null

.PHONY: help up down logs elastic-index

##@-- Core

help: ##@ Show available targets
	@printf '%s\n' \
	'# Set default section and ANSI colors.' \
	'BEGIN {' \
	'	FS = ":.*?##@"' \
	'	sec = "General"' \
	'	sc = "\033[1;33m"' \
	'	tc = "\033[1;32m"' \
	'	r = "\033[0m"' \
	'}' \
	'# Capture section headers like "##@-- Title".' \
	'/^##@--/ {' \
	'	sec = $$0' \
	'	sub(/^##@--[[:space:]]*/, "", sec)' \
	'	if (!seen[sec]++) {' \
	'		order[++n] = sec' \
	'	}' \
	'	next' \
	'}' \
	'# Capture targets and their help text.' \
	'/^[a-zA-Z0-9_.-]+:.*?##@/ {' \
	'	if (!seen[sec]++) {' \
	'		order[++n] = sec' \
	'	}' \
	'	cmd = $$1' \
	'	help = $$2' \
	'	if (length(cmd) > max) {' \
	'		max = length(cmd)' \
	'	}' \
	'	data[sec, ++count[sec]] = cmd SUBSEP help' \
	'}' \
	'# Print sections and aligned target help.' \
	'END {' \
	'	for (i = 1; i <= n; i++) {' \
	'		s = order[i]' \
	'		if (!(s in count)) {' \
	'			continue' \
	'		}' \
	'		printf "%s%s%s\n", sc, s, r' \
	'		for (j = 1; j <= count[s]; j++) {' \
	'			split(data[s, j], p, SUBSEP)' \
	'			printf "  %s%-*s%s\t%s\n", tc, max, p[1], r, p[2]' \
	'		}' \
	'		printf "\n"' \
	'	}' \
	'}' \
	| awk -f - $(MAKEFILE_LIST)

up: ##@ Start services (detached)
	$(STACK_CMD) up -d

down: ##@ Stop services
	$(STACK_CMD) down

log: ##@ Follow service logs
	$(STACK_CMD) logs -f

##@-- Maintenance

ei: ##@ Rebuild elastic index for dev_tenant inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:elastic:index --fresh dev_tenant

cc: ##@ Clear application cache inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) cache:clear

rs: ##@ Restart Swoole inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) octane:reload
	#$(STACK_CMD) $(SERVICE_EXEC) sv restart swoole-http # old way

reload-env: ##@ Recreate the web container to pick up .env changes
	$(STACK_CMD) up -d --force-recreate $(APP_SERVICE)

list-services: ##@ List all running containers
	$(STACK_CMD) $(SERVICE_EXEC) ls -1 /etc/service

tinker: ##@ Open Tinker REPL, or run inline PHP with EXECUTE='code'
	$(STACK_CMD) $(SERVICE_ARTISAN) tinker $(if $(EXECUTE),--execute '$(EXECUTE)',)

NVM_DIR ?= $(HOME)/.nvm
NVM_SH := $(NVM_DIR)/nvm.sh

##@-- Development

cocoindex-update: ##@ Update cocoindex for dev_tenant inside the web container
	cd cocoindex && source .venv/bin/activate && cocoindex update main.py && deactivate

frontend: ##@ Start frontend development server - once built files will remain on host machine
	cd sonar && \
	if [ -s "$(NVM_SH)" ]; then \
		. "$(NVM_SH)"; \
	else \
		echo "nvm not found at $(NVM_SH); install nvm or set NVM_DIR." >&2; \
		exit 127; \
	fi; \
	nvm use 16.20.2 && yarn frontend

seed.demo: ##@ Seed database with test data inside the web container - May fail just requires the "/sonar/storage/app/uploaded_files/" to be present. 
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:seed:demo dev_tenant

reset: ##@ Reset the development environment
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:dev:reset

enable:
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:instance:setenabled dev_tenant

migration.create: ##@ Run database migrations inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:make:migration $(word 2,$(MAKECMDGOALS))

migration.migrate: ##@ Run database migrations inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:migrate

task-create: ##@ Create a new task class inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) make:upgradetask --deferred $(word 2,$(MAKECMDGOALS))

pug: ##@ Run PHPUnit with a group filter inside the web container
	$(STACK_CMD) $(SERVICE_EXEC) ./vendor/bin/phpunit  --group $(word 2,$(MAKECMDGOALS))

pug-quiet: ##@ Run PHPUnit with a group, hiding warnings/deprecations
	$(STACK_CMD) $(SERVICE_EXEC) ./vendor/bin/phpunit --group $(word 2,$(MAKECMDGOALS)) --no-output-on-warning --no-output-on-deprecation

puf: ##@ Run PHPUnit with a filter inside the web container
	$(STACK_CMD) $(SERVICE_EXEC) ./vendor/bin/phpunit  --filter $(word 2,$(MAKECMDGOALS))

puf-quiet: ##@ Run PHPUnit with a filter, hiding warnings/deprecations
	$(STACK_CMD) $(SERVICE_EXEC) ./vendor/bin/phpunit --filter $(word 2,$(MAKECMDGOALS)) --no-output-on-warning --no-output-on-deprecation

cs-fix: ##@ Run PHP CS Fixer inside the web container
	$(STACK_CMD) $(SERVICE_EXEC) ./vendor/bin/phpcbf -d memory_limit=2G --extensions=php -ns --parallel=4 --standard=phpcs.xml app tests

ide-helper: ##@ Generate Laravel IDE helper files inside the web container
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:ide-helper
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:ide-helper --models

artisan: ##@ Run artisan command inside the web container - make artisan migrate:status
	$(STACK_CMD) $(SERVICE_ARTISAN) $(word 2,$(MAKECMDGOALS))

##@-- Billing

enable-daily-billing: ##@ Enable daily billing
	make tinker-execute-script SCRIPT=enableDailyBilling

invoice-delinquent: ##@ Mark invoices as delinquent
	make tinker-execute-script SCRIPT=invoiceDelinquent
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:billing:delinquency

invoice-compliant: ##@ Mark invoices as compliant
	make tinker-execute-script SCRIPT=invoiceCompliant
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:billing:delinquency

billing.run: ##@ runs billing for dev_tenant for 2026-05-01 (date may need to be updated in the future)
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:billing:run dev_tenant 2026-02-01

autopay.run: ##@ runs autopay for dev_tenant for 2026-01-01 (date may need to be updated in the future)
	$(STACK_CMD) $(SERVICE_ARTISAN) sonar:billing:autopay dev_tenant 2026-02-01

##@-- Utilities

activate-account: ##@ Creates a new user account and activates it
	make tinker-execute-script SCRIPT=activateAccount

update-vehicle-location: ##@ Adds a new vehicle location entry
	make tinker-execute-script SCRIPT=trackVehicle

add-new-user: ##@ Adds a new user to the system
	make tinker-execute-script SCRIPT=addNewUser

tinker-test: ##@ A test script that can be used for anything
	make tinker-execute-script SCRIPT=testTinker

# Use artisan command
#activate-instance: ##@ Activates instance with id 1
	#make tinker-execute-script SCRIPT=activateInstance

#deactivate-instance: ##@ Deactivates user account with id 1
#	make tinker-execute-script SCRIPT=disableInstance

##@-- Helper methods

# Prevent Make from treating the argument as a target - used in pug (methods that takes an argument) for arguments without a name
%:
	@:

tinker-execute-script: ##@ A helper method to run custom tinker scripts. Usage: make tinker-execute-script SCRIPT=scriptName
	$(STACK_CMD) $(SERVICE_ARTISAN) tinker --execute 'require app_path("TinkerScripts/$(SCRIPT).php");'
