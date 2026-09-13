# Observability — Context Skill

## What this pattern is
Observability combines safe logging, trace propagation, execution markers, and runtime monitoring so you can explain what happened without leaking sensitive data. In this style of service, logs must be structured, correlated, and safe by default. 

Observability guide for Java/Spring microservices. It covers secure logging, distributed tracing, metrics, and logback configuration.

Core principle: **use a structured, masking-aware logger, never plain SLF4J directly in application code**. The logging layer must help mask or avoid sensitive output.

## How to apply it

### 1. SecureLogger — Mandatory secure logging
This project uses a `SecureLogger` wrapper (illustrative name — implement your own or use a shared library) instead of direct SLF4J. It automatically masks sensitive data (account numbers, amounts, tokens).

```java
// ✅ CORRECT
@RequiredArgsConstructor
public class TransferUseCase implements TransferPort {
    private final SecureLogger log = new SecureLogger(TransferUseCase.class);

    public Mono<TransferResult> apply(TransferCommand command) {
        return coreBankingPort.execute(command)
            .doOnSuccess(r -> log.info("Transfer applied: txId={}", r.transactionId()))
            .doOnError(ex -> log.error("Transfer failed for cif={}", command.cif(), ex));
    }
}

// ❌ INCORRECT — direct SLF4J can expose sensitive data
private static final Logger log = LoggerFactory.getLogger(TransferUseCase.class);
log.info("Transfer for account={}", command.account()); // ← account number in clear text
```

### What to log vs what NOT to log

| ✅ Log | ❌ DO NOT log |
|---|---|
| `transactionId`, `operationId` | Full account numbers |
| `cif` (client identifier) | Exact transaction amount |
| Error code | OAuth / JWT tokens |
| Operation duration | Passwords / secrets |
| `traceparent` / `traceId` | Full personal data |

### 2. @LogExecution — Endpoint traceability
AOP annotation to automatically log the start/end of each endpoint:

```java
@Override
@LogExecution(actionId = "<service>-<operation>")
public Mono<ResponseEntity<ResponseDto<TransferResponseDto>>> apply(
        @RequestHeader(TOKEN_HEADER) String token,
        @RequestHeader(CHANNEL_HEADER) String channel,
        @Valid @RequestBody TransferRequestDto request) {
    return transferPort.apply(mapper.toCommand(request, token, channel))
        .map(result -> ResponseEntity.ok(ResponseDto.of(mapper.toResponse(result))));
}
```

**`actionId` convention:** `<service-name>-<operation-name>`
Examples: `transfer-local-apply`, `clients-get-product-tree`

### 3. Context propagation (traceparent)
The W3C `traceparent` connects the logs of all microservices into a single trace:

```yaml
# application.yml — standard configuration
app:
  reactive-context:
    enabled: true
    headers:
      - traceparent
      - channel
      - x-device-id
      - True-Client-IP
```

```java
// Bootstrap — enable automatic Reactor context propagation
@PostConstruct
public void init() {
    Hooks.enableAutomaticContextPropagation();
}
```

### Preserve context in fire-and-forget flows
For background operations, propagate the context manually:

```java
Mono.deferContextual(ctx -> {
    backgroundOp()
        .contextWrite(ctx)  // ← propagates traceparent to the background
        .subscribeOn(Schedulers.boundedElastic())
        .subscribe();
    return Mono.just(result);
})
```

### 4. Logback configuration

#### logback-spring.xml (Standard pattern)

```xml
<configuration>
  <!-- Console for local and test profiles -->
  <springProfile name="local,test">
    <appender name="CONSOLE" class="ch.qos.logback.core.ConsoleAppender">
      <encoder>
        <pattern>%d{yyyy-MM-dd HH:mm:ss} [%X{traceId:-}-%X{spanId:-}] %-5level %logger{36} - %msg%n</pattern>
      </encoder>
    </appender>
    <root level="INFO"><appender-ref ref="CONSOLE"/></root>
  </springProfile>

  <!-- Structured JSON for non-local (ECS, production) -->
  <springProfile name="!local &amp; !test">
    <appender name="JSON" class="ch.qos.logback.core.ConsoleAppender">
      <encoder class="net.logstash.logback.encoder.LogstashEncoder">
        <customFields>{"service":"${spring.application.name}"}</customFields>
      </encoder>
    </appender>
    <root level="INFO"><appender-ref ref="JSON"/></root>
  </springProfile>
</configuration>
```

#### Standard fields in JSON logs (non-local)

| Field | Source | Usage |
|---|---|---|
| `timestamp` | logback | Event time |
| `log_level` | logback | INFO / ERROR / DEBUG |
| `trace_id` | MDC `%X{traceId}` | Correlation with your APM tool |
| `span_id` | MDC `%X{spanId}` | Sub-operation |
| `message` | log call | Event description |
| `service` | customFields | Microservice name |

### 5. Log levels by context

| Level | When |
|---|---|
| `INFO` | Start and end of main operations, lifecycle milestones, success |
| `DEBUG` | Per-element details in lists, intermediate state |
| `ERROR` | Captured errors with stacktrace |
| `WARN` | Unusual but recoverable situation |

```java
// ✅ INFO pattern for flow milestones
log.info("Transfer initiated: cif={}, currency={}", command.cif(), command.currency());

// ✅ DEBUG for per-element details
accounts.forEach(acc -> log.debug("Processing account: id={}", acc.id()));

// ✅ ERROR with exception
.doOnError(ex -> log.error("Core banking call failed: txId={}", txId, ex))
```

### 6. Observability in production

#### Tools by use case

| Tool category | To answer |
|---|---|
| **APM** (e.g. Dynatrace, Datadog, New Relic) | Where is the bottleneck? Why is it slow? Latency per layer |
| **Log aggregation** (e.g. CloudWatch, Loki, ELK) | What payload arrived? What exact stacktrace was generated? |

#### Metrics (Micrometer + Actuator)

```yaml
# application.yml
management:
  endpoints:
    web:
      exposure:
        include: health,metrics,prometheus
  metrics:
    tags:
      application: ${spring.application.name}
```

```xml
<!-- pom.xml -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
<!-- Add your APM vendor's Micrometer registry dependency here if applicable -->
```

### Observability Anti-patterns

| Anti-pattern (❌) | Correction (✅) |
|---|---|
| Direct `LoggerFactory.getLogger()` | Use `new SecureLogger(MyClass.class)` |
| Logging full account numbers or tokens | Only log opaque identifiers and error codes |
| No `@LogExecution` on endpoints | Add to all controller methods |
| No `contextWrite(ctx)` in fire-and-forget | Always propagate context in background ops explicitly |
| Logs only in development (no logstash) | Configure non-local profile with JSON encoder |
| `traceparent` not configured | Add to `app.reactive-context.headers` |
| Using DEBUG for major milestones | Use INFO for milestones |
| ERROR log without stacktrace or identifiers | Include exception and safe correlation fields |
