import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from main import (
    extract_php_metadata,
    detect_laravel_layer,
    get_chunk_params,
    extract_method_name_from_chunk,
)


def test_detect_layer_service():
    assert detect_laravel_layer("app/Services/BillingService.php") == "service"


def test_detect_layer_controller():
    assert detect_laravel_layer("app/Http/Controllers/AccountController.php") == "controller"


def test_detect_layer_job():
    assert detect_laravel_layer("app/Jobs/ProcessInvoice.php") == "job"


def test_detect_layer_request():
    assert detect_laravel_layer("app/Http/Requests/CreateAccountRequest.php") == "request"


def test_detect_layer_graphql():
    assert detect_laravel_layer("app/GraphQL/Mutations/CreateAccount.php") == "graphql"


def test_detect_layer_console():
    assert detect_laravel_layer("app/Console/Commands/ProcessBilling.php") == "console"

def test_detect_layer_event():
    assert detect_laravel_layer("app/Events/InvoiceCreated.php") == "event"

def test_detect_layer_listener():
    assert detect_laravel_layer("app/Listeners/SendInvoiceEmail.php") == "listener"

def test_detect_layer_notification():
    assert detect_laravel_layer("app/Notifications/InvoiceGenerated.php") == "notification"

def test_detect_layer_observer():
    assert detect_laravel_layer("app/Observers/AccountObserver.php") == "observer"

def test_detect_layer_provider():
    assert detect_laravel_layer("app/Providers/AppServiceProvider.php") == "provider"

def test_detect_layer_model_root():
    assert detect_laravel_layer("/sonar/app/Account.php") == "model"

def test_detect_layer_model_subdir():
    assert detect_laravel_layer("/sonar/app/Models/Account.php") == "model"

def test_detect_layer_other():
    assert detect_laravel_layer("/sonar/app/Support/SomeHelper.php") == "other"


def test_extract_metadata_full():
    content = "<?php\nnamespace App\\Services;\n\nclass BillingService extends BaseService\n{\n    public function calculateTax() {}\n}"
    meta = extract_php_metadata(content, "app/Services/BillingService.php")
    assert meta["class_name"] == "BillingService"
    assert meta["namespace"] == "App\\Services"
    assert meta["layer_type"] == "service"


def test_extract_metadata_missing_namespace():
    content = "<?php\nclass SimpleHelper {}"
    meta = extract_php_metadata(content, "app/Helpers/SimpleHelper.php")
    assert meta["class_name"] == "SimpleHelper"
    assert meta["namespace"] is None


def test_chunk_params_service_within_model_window():
    params = get_chunk_params('service')
    assert params['chunk_size'] <= 1500, "service chunk_size must fit krlvi 512-token window (~1800 chars)"
    assert params['chunk_size'] >= 800


def test_chunk_params_job_within_model_window():
    params = get_chunk_params('job')
    assert params['chunk_size'] <= 1500, "job chunk_size must fit krlvi 512-token window (~1800 chars)"
    assert params['chunk_size'] >= 1000


def test_chunk_params_other_default():
    params = get_chunk_params('other')
    assert params['chunk_size'] <= 1000
    assert params['chunk_size'] >= 600


def test_extract_method_name_finds_method():
    chunk = "    public function calculateTax(array $items): float\n    {\n        return 0.0;\n    }"
    assert extract_method_name_from_chunk(chunk) == "calculateTax"


def test_extract_method_name_no_method():
    chunk = "<?php\nnamespace App\\Services;\nuse Illuminate\\Support\\Collection;"
    assert extract_method_name_from_chunk(chunk) is None
