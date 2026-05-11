import { test } from 'node:test';
import assert from 'node:assert/strict';
import { extractPhpMetadata, detectLaravelLayer } from '../metadata.js';

test('detectLaravelLayer service', () => {
  assert.equal(detectLaravelLayer('app/Services/BillingService.php'), 'service');
});

test('detectLaravelLayer controller', () => {
  assert.equal(detectLaravelLayer('app/Http/Controllers/AccountController.php'), 'controller');
});

test('detectLaravelLayer job', () => {
  assert.equal(detectLaravelLayer('app/Jobs/ProcessInvoice.php'), 'job');
});

test('detectLaravelLayer request', () => {
  assert.equal(detectLaravelLayer('app/Http/Requests/CreateAccount.php'), 'request');
});

test('detectLaravelLayer graphql', () => {
  assert.equal(detectLaravelLayer('app/GraphQL/Mutations/CreateAccount.php'), 'graphql');
});

test('detectLaravelLayer other', () => {
  assert.equal(detectLaravelLayer('app/Models/Account.php'), 'other');
});

test('detectLaravelLayer frontend', () => {
  assert.equal(detectLaravelLayer('sonar/ui/app/components/Account.vue'), 'frontend');
});

test('extractPhpMetadata full', () => {
  const content = '<?php\nnamespace App\\Services;\n\nclass BillingService {}';
  const result = extractPhpMetadata(content, 'app/Services/BillingService.php');
  assert.equal(result.className, 'BillingService');
  assert.equal(result.namespace, 'App\\Services');
  assert.equal(result.layerType, 'service');
});

test('extractPhpMetadata missing namespace', () => {
  const content = '<?php\nclass SimpleHelper {}';
  const result = extractPhpMetadata(content, 'app/Helpers/SimpleHelper.php');
  assert.equal(result.className, 'SimpleHelper');
  assert.equal(result.namespace, null);
});
