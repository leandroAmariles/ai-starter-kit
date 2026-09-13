# Reactive Programming — Context Skill

## What this pattern is
Reactive programming with Project Reactor and Spring WebFlux models work as asynchronous pipelines using `Mono` and `Flux`. The goal is end-to-end non-blocking behavior: controllers, use cases, adapters, and integrations all compose signals instead of waiting imperatively.

This is the default programming model shipped with this starter kit's Java/Spring profile, for services that are 100% reactive.

The absolute rule: **ZERO `.block()` in production code**. Once one layer blocks, the whole reactive chain loses its scalability and context propagation benefits.

## How to apply it

### 1. Build use cases as a single composed chain
Standard shape:
1. map external input into a domain command
2. validate or enrich
3. call outbound ports
4. transform to result
5. add logging with side-effect operators
6. translate failures with reactive error operators

```java
public Mono<OperationResult> execute(OperationCommand command) {
    return authorizationPort.check(command.userId(), Permission.OPERATION)
        .then(customerLookupPort.findByCif(command.cif()))
        .switchIfEmpty(Mono.error(new BusinessException(ErrorCode.MS<SERVICE>_GE_00002)))
        .flatMap(customer -> executionPort.execute(command, customer))
        .flatMap(persistencePort::save)
        .map(resultMapper::toResult)
        .doOnSuccess(result -> secureLogger.info("Operation completed: transactionId={}", result.transactionId()))
        .doOnError(error -> secureLogger.error("Operation failed", error))
        .onErrorMap(TimeoutException.class,
            error -> new TechnicalException(ErrorCode.MS<SERVICE>_GE_00010, error));
}
```

### 2. Use the right core operators

#### `flatMap`
Use when the next step returns `Mono` or `Flux` (asynchronous operations).

```java
return accountPort.findById(command.accountId())
    .flatMap(account -> limitsPort.validate(account, command.amount()))
    .flatMap(valid -> executionPort.execute(command));
```

#### `map`
Use for synchronous transformation only (no I/O).

```java
return executionPort.execute(command)
    .map(resultMapper::toResponse);
```

#### `switchIfEmpty`
Convert empty publisher cases into domain behavior or default values (replaces null checks).

```java
return customerLookupPort.findByCif(command.cif())
    .switchIfEmpty(Mono.error(new BusinessException(ErrorCode.MS<SERVICE>_GE_00003)));
```

#### `onErrorMap` and `onErrorResume`
*   `onErrorMap`: translate exception type
*   `onErrorResume`: recover or return fallback flow

```java
return externalPort.call(command)
    .onErrorMap(WebClientResponseException.class,
        error -> new TechnicalException(ErrorCode.MS<SERVICE>_DP_00001, error))
    .onErrorResume(RoleNotAllowedException.class,
        error -> Mono.error(new BusinessException(ErrorCode.AUTH_ROLE_00001, error)));
```

#### `doOnSuccess` / `doOnError` / `doOnNext`
Use only for side effects such as logging or metrics. Do NOT use them for business logic.

```java
return processPort.execute(command)
    .doOnSuccess(result -> secureLogger.info("Finished reference={}", result.reference()))
    .doOnError(error -> secureLogger.error("Failure", error));
// ❌ NEVER put business logic in doOnNext
```

#### `Mono.zip`
Use for parallel independent calls.

```java
return Mono.zip(
        customerPort.findByCif(command.cif()),
        catalogPort.getOperationCatalog(command.operationType()),
        limitsPort.getLimits(command.cif()))
    .flatMap(tuple -> executionPort.execute(command, tuple.getT1(), tuple.getT2(), tuple.getT3()));
```

#### `then` and `thenReturn`
Use when one step's value is not needed but its completion is (sequencing without return).

```java
return auditPort.save(command)
    .then(executionPort.execute(command))
    .thenReturn(OperationAcknowledgement.success());
```

#### `Flux.fromIterable(...).collectList()`
Use to process a collection reactively and return it as a list.

```java
return Flux.fromIterable(command.references())
    .flatMap(statusPort::findByReference)
    .map(statusMapper::toItem)
    .collectList();
```

### 3. Never block
Forbidden in application code:
*   `.block()`
*   `.blockOptional()`
*   `.blockFirst()`
*   `.blockLast()`
*   `Thread.sleep()` inside reactive flow

### 4. Fire-and-forget safely (Kafka / background events)
When an event, audit task, or notification should run in background and must not break the client response, use this pattern:

```java
return executionPort.execute(command)
    .flatMap(result -> Mono.deferContextual(ctx -> {
        eventPublisherPort.publish(new OperationEvent(result.transactionId(), command.cif()))
            .contextWrite(ctx)                        // propagates traceparent + headers
            .subscribeOn(Schedulers.boundedElastic())  // separate thread pool
            .onErrorResume(error -> {
                secureLogger.error("Async publish failed", error);
                return Mono.empty();  // absorbs the error, doesn't cancel response
            })
            .subscribe();                              // starts in background

        return Mono.just(result);                     // responds to client immediately
    }));
```

**Rules for fire-and-forget:**
1. Always `deferContextual` to capture Reactor context.
2. Always `contextWrite(ctx)` to propagate `traceparent` and headers.
3. Always `subscribeOn(Schedulers.boundedElastic())` — never on the request thread.
4. Always `onErrorResume` returning `Mono.empty()` — never leave silent errors.

### 5. Enable and preserve reactive context propagation
At bootstrap time:

```java
@PostConstruct
public void init() {
    Hooks.enableAutomaticContextPropagation();
}
```

In configuration:

```yaml
app:
  reactive-context:
    enabled: true
    headers:
      - traceparent
      - channel
      - x-device-id
```

### 6. Resilience with Resilience4j (WebFlux)
Apply resilience at adapter/integration boundaries. If your organization has a shared resilience
library that already wraps, manages, and enforces circuit-breaker/retry/timeout concerns globally,
prefer delegating to it over hand-rolled annotations scattered across the codebase — your
responsibility then becomes proper configuration (e.g., via `application.yml` properties) rather than
re-implementing the mechanism per adapter.

### ❌ Don't: Scatter ad-hoc resilience annotations across adapters

```java
// ❌ ANTI-PATTERN: Inconsistent, per-adapter resilience config instead of a shared, centrally configured policy
@CircuitBreaker(name = "external-service", fallbackMethod = "fallback")
@Retry(name = "external-service")
@TimeLimiter(name = "external-service")
public Mono<ProviderResponse> execute(ProviderRequest request) {
    return webClient.post().uri("/operations")...
}
```

### Reactive Anti-patterns to avoid

| Anti-pattern (❌) | Impact | Correction (✅) |
|---|---|---|
| `.block()` anywhere in production flow | Exhausts Netty thread pool → total degradation | Compose with `flatMap`, `map`, `zip`, `then` |
| Business logic inside `doOnNext` / `doOnSuccess` | Side-effect operators are not guaranteed | Keep business steps in `map`/`flatMap` |
| Using `map` when the lambda returns `Mono` | Produces nested publishers | Use `flatMap` |
| Ignoring empty results or returning `null` | Silent no-op or NPE | Use `switchIfEmpty`, `defaultIfEmpty` |
| `.subscribe()` without `onErrorResume` | Silent errors | Add error handling |
| Fire-and-forget without `contextWrite(ctx)` | Loses tracing and contextual headers | Use `deferContextual` + `contextWrite` |
| Fire-and-forget without `subscribeOn` | Can consume request thread resources | Use `subscribeOn(Schedulers.boundedElastic())` |
| Sequential independent remote calls | Adds unnecessary latency | Use `Mono.zip` for parallelism |
| `Thread.sleep()` in tests | Flaky tests | Use `StepVerifier.withVirtualTime` |
