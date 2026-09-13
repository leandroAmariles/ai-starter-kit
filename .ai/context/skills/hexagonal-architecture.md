# Hexagonal Architecture — Context Skill

## What this pattern is

Hexagonal architecture separates business rules from delivery and infrastructure concerns so the domain can evolve without depending on HTTP, databases, message brokers, or framework annotations. A common implementation in Java uses a multi-module Maven layout where the domain defines contracts and use cases, infrastructure implements those contracts, and the application module wires everything together explicitly.

This is the default architecture pattern shipped with this starter kit's Java/Spring profile. Absorbing this skill allows the agent to generate structurally correct code without additional instructions — adapt the module names below to your own project's conventions.

### Maven Module Structure

A common mandatory multi-module structure:

```text
<service-name>/
├── domain/
│   ├── model/           ← Entities (Records), IN/OUT Ports, ErrorCode, Domain Mappers
│   └── usecase/         ← IN Port implementations, Decorators, Facades
├── infrastructure/
│   ├── in/
│   │   └── rest/        ← WebFlux Controllers, REST DTOs, REST Mappers, GlobalExceptionHandler
│   └── out/
│       ├── external/    ← Adapter for an external system (e.g. core banking, ERP, a third-party API)
│       ├── persistence/ ← Database Adapter (e.g. PostgreSQL R2DBC)
│       ├── cache/       ← Cache Adapter (e.g. Redis)
│       ├── authorization/ ← Authorization Adapter (if your project has fine-grained authz)
│       └── eventpublisher/ ← Event/messaging Adapter (e.g. Kafka)
├── helper/
│   └── exception/       ← Exception hierarchy + ErrorCode enum
└── application/         ← @SpringBootApplication Bootstrap + ServiceConfiguration
```
> **Note:** Some projects use `infraestructure` (a historical typo) — respect the convention of the current project.

## How to apply it

### Rules by layer

#### `domain/model/` — Pure Domain
*   **ZERO** Spring annotations (`@Service`, `@Component`, `@Autowired`, `@Repository`)
*   Entities as Java `record` with `@Builder(toBuilder = true)`
*   IN Ports: Interfaces implemented by use cases
*   OUT Ports: Interfaces used by use cases to access infrastructure
*   Mappers: Static constants `INSTANCE = Mappers.getMapper(...)`

```java
// ✅ Domain entity
@Builder(toBuilder = true)
public record TransferCommand(
    String originAccount,
    String targetAccount,
    BigDecimal amount,
    String currency,
    String channel
) {}

// ✅ IN Port — interface implemented by the use case
public interface TransferPort {
    Mono<TransferResult> apply(TransferCommand command);
}

// ✅ OUT Port — interface used by the use case
public interface ExternalServicePort {
    Mono<ExternalServiceResult> executeTransfer(TransferCommand command);
}
```

#### `domain/usecase/` — Business Logic
*   Only `@RequiredArgsConstructor` (no `@Service`, `@Component`)
*   Inject ONLY OUT Ports (interfaces, never concrete classes)
*   Use your structured/masking logger instead of `LoggerFactory.getLogger()` (see `observability.md`)
*   If it has > 5 dependencies → apply the **Facade** pattern

```java
@RequiredArgsConstructor
public class TransferUseCase implements TransferPort {

    private final SecureLogger log = new SecureLogger(TransferUseCase.class);
    private final ExternalServicePort externalServicePort;
    private final AuthorizationPort authorizationPort;
    private final EventPublisherPort eventPublisherPort;

    @Override
    public Mono<TransferResult> apply(TransferCommand command) {
        return authorizationPort.check(command.originAccount(), Permission.TRANSFER)
            .flatMap(__ -> externalServicePort.executeTransfer(command))
            .doOnSuccess(r -> log.info("Transfer applied: txId={}", r.transactionId()))
            .doOnError(ex -> log.error("Transfer failed", ex));
    }
}
```

#### Decorator Pattern (Security / Encryption)
To encrypt/decrypt sensitive fields without polluting the use case:

```java
@RequiredArgsConstructor
public class TransferSecureDecorator implements TransferPort {
    private final TransferPort delegate;

    @Override
    @SecureCrypto(CryptoAlgorithm.AES)  // AOP handles encryption
    public Mono<TransferResult> apply(TransferCommand command) {
        return delegate.apply(command);  // ONLY delegates, no custom logic
    }
}
```

#### Facade Pattern (Dependency Reduction)
When a use case exceeds 5 dependencies, group the related ones:

```java
@RequiredArgsConstructor
public class TransferValidationFacade {
    private final AuthorizationPort authorizationPort;
    private final AccountPort accountPort;
    private final ServiceCodePort serviceCodePort;

    public Mono<AccountData> validateAndGet(String customerId, String accountId) {
        return authorizationPort.check(customerId, Permission.TRANSFER)
            .flatMap(__ -> accountPort.findAccount(customerId, accountId))
            .switchIfEmpty(Mono.error(new AccountNotFoundException(accountId)));
    }
}
```

#### `infrastructure/in/rest/` — Input Layer
```java
@Component
@RequiredArgsConstructor
public class TransferControllerImpl implements TransferController {

    private final TransferPort transferPort;  // Injects the @Primary (Decorator)
    private final TransferControllerMapper mapper;

    @Override
    @LogExecution(actionId = "<service>-transfer-apply")
    public Mono<ResponseEntity<ResponseDto<TransferResponseDto>>> apply(
            @RequestHeader(TOKEN_HEADER) String token,
            @RequestHeader(CHANNEL_HEADER) @NotBlank String channel,
            @Valid @RequestBody TransferRequestDto request) {
        return transferPort.apply(mapper.toCommand(request, token, channel))
            .map(result -> ResponseEntity.ok(ResponseDto.of(mapper.toResponse(result))));
    }
}
```

#### `infrastructure/out/` — Output Adapters
*   `@Component` is only used in this layer
*   Implements OUT Ports of the domain
*   Use `onErrorMap`/`onErrorResume` to translate external exceptions

#### `application/ServiceConfiguration` — Manual Wiring
```java
@Configuration
@RequiredArgsConstructor
public class ServiceConfiguration {

    // OUT Ports auto-injected from infrastructure/out
    private final ExternalServicePort externalServicePort;
    private final AuthorizationPort authorizationPort;
    private final EventPublisherPort eventPublisherPort;

    @Bean
    public TransferPort transferUseCase() {
        return new TransferUseCase(externalServicePort, authorizationPort, eventPublisherPort);
    }

    @Bean
    @Primary
    public TransferPort transferSecureDecorator(
            @Qualifier("transferUseCase") TransferPort transferUseCase) {
        return new TransferSecureDecorator(transferUseCase);
    }
}
```

### Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Classes | `PascalCase` | `TransferUseCase`, `ExternalServiceAdapter` |
| IN Ports | `<Domain>Port` | `TransferPort`, `AccountPort` |
| OUT Ports | `<System><Domain>Port` | `ExternalServiceTransferPort`, `AuthorizationPort` |
| Use Cases | `<Domain>UseCase` | `TransferUseCase` |
| Adapters | `<Domain>Adapter` | `ExternalServiceTransferAdapter` |
| Decorators | `<Domain>SecureDecorator` | `TransferSecureDecorator` |
| Facades | `<Domain>ValidationFacade` | `TransferValidationFacade` |
| Methods | `camelCase` | `executeTransfer`, `findAccount` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS` |

### Standard Implementation Flow (Layer Order)
1. REST Controller Interface + Request/Response DTOs
2. Controller Implementation
3. REST Mapper (MapStruct)
4. IN Port in `domain/model/port/in/`
5. Wiring in `ServiceConfiguration`
6. Decorator (if there are sensitive fields)
7. Use Case in `domain/usecase/`
8. OUT Port in `domain/model/port/out/`
9. Adapter in `infrastructure/out/`
10. Tests: UseCase + Controller + Adapter

### Anti-patterns to avoid

| Anti-pattern (❌) | Correction (✅) |
|---|---|
| `@Service` on use case | Manual wiring via `@Bean` in `ServiceConfiguration` |
| Injecting a concrete class in use case | Inject the interface (OUT Port) |
| Business logic in controller | Delegate to the IN Port |
| Business logic in Decorator | Only delegate with `@SecureCrypto` / cross-cutting concerns |
| `@Autowired` in production | Constructor injection via `@RequiredArgsConstructor` |
| > 5 dependencies in use case | Apply the Facade pattern |
| Direct SLF4J in the domain | Use your structured/masking logger |
| Domain port returning transport DTOs | Use domain commands, results, and value objects |
