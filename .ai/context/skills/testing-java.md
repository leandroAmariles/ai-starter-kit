# Testing Java — Context Skill

## What this pattern is
The testing approach mirrors the production architecture so failures are isolated by layer: use case tests prove domain orchestration, controller tests prove REST contracts, adapter tests prove infrastructure integration, and a minimal smoke test proves Spring wiring. New code should target **100% coverage on the added behavior**, even if the whole repository uses a lower global threshold.

Testing guide for Java/Spring microservices with JUnit 5, Mockito, StepVerifier, and WebFluxTest.

### Module Test Structure
Tests are located mirroring the production structure:

```text
domain/usecase/src/test/java/    ← Use case tests (unit, Mockito + StepVerifier)
infrastructure/in/rest/src/test/ ← Controller tests (@WebFluxTest + WebTestClient)
infrastructure/out/*/src/test/   ← Adapter tests (unit + WireMock)
application/src/test/java/       ← Smoke test @SpringBootTest
```

## How to apply it

### Use Case Tests (Standard Pattern)
Use case tests should not start Spring, they must be pure unit tests.

```java
@ExtendWith(MockitoExtension.class)
class TransferUseCaseTest {

    @Mock private ExternalServicePort externalServicePort;
    @Mock private AuthorizationPort authorizationPort;
    @Mock private EventPublisherPort eventPublisherPort;

    @InjectMocks private TransferUseCase useCase;

    @Test
    void should_apply_transfer_successfully() {
        // Arrange
        when(authorizationPort.check(anyString(), any())).thenReturn(Mono.empty());
        when(externalServicePort.executeTransfer(any())).thenReturn(Mono.just(mockResult()));
        when(eventPublisherPort.publish(any())).thenReturn(Mono.empty());

        // Act + Assert
        StepVerifier.create(useCase.apply(buildCommand()))
            .expectNextMatches(r -> r.transactionId() != null)
            .verifyComplete();
    }

    @Test
    void should_propagate_error_when_external_service_fails() {
        when(authorizationPort.check(anyString(), any())).thenReturn(Mono.empty());
        when(externalServicePort.executeTransfer(any()))
            .thenReturn(Mono.error(new BusinessException(ErrorCode.EXTERNAL_SERVICE_ERROR)));

        StepVerifier.create(useCase.apply(buildCommand()))
            .expectError(BusinessException.class)
            .verify();
    }
}
```

**Rules:**
*   Always use `@ExtendWith(MockitoExtension.class)` for unit tests
*   Mock the OUT Ports, never concrete implementations
*   One success case (`verifyComplete()`) + at least one error case (`expectError()`) per main flow
*   NEVER use `.block()` or `Thread.sleep()` in tests

### Capturing arguments
Use `ArgumentCaptor` when you need to verify the exact object passed to a port or collaborator.

```java
@Captor ArgumentCaptor<TransferCommand> commandCaptor;

@Test
void should_capture_mapper_output() {
    // ...
    verify(externalServicePort).executeTransfer(commandCaptor.capture());
    assertThat(commandCaptor.getValue().amount())
        .isEqualByComparingTo(BigDecimal.valueOf(100));
}
```

### Controller Tests (@WebFluxTest)

```java
@WebFluxTest(TransferControllerImpl.class)
@Import(GlobalExceptionHandler.class)
class TransferControllerImplTest {

    @Autowired private WebTestClient webTestClient;
    @MockitoBean private TransferPort transferPort;

    @Test
    void should_return_200_when_transfer_succeeds() {
        when(transferPort.apply(any())).thenReturn(Mono.just(mockResult()));

        webTestClient.post().uri("/apply")
            .header("Accept-Version", "1.0.0")
            .header(TOKEN_HEADER, "test-token")
            .header(CHANNEL_HEADER, "mobile")
            .bodyValue(buildRequest())
            .exchange()
            .expectStatus().isOk()
            .expectBody()
            .jsonPath("$.data.transactionId").isNotEmpty();
    }

    @Test
    void should_return_403_when_role_not_allowed() {
        when(transferPort.apply(any()))
            .thenReturn(Mono.error(new RoleNotAllowedException("AUTH_ROLE_00001")));

        webTestClient.post().uri("/apply")
            .header("Accept-Version", "1.0.0")
            .header(TOKEN_HEADER, "test-token")
            .header(CHANNEL_HEADER, "mobile")
            .bodyValue(buildRequest())
            .exchange()
            .expectStatus().isForbidden()
            .expectBody()
            .jsonPath("$.errors[0].code").isEqualTo("AUTH_ROLE_00001");
    }
}
```

**Rules:**
*   Always `@Import(GlobalExceptionHandler.class)` — verifies real HTTP mapping
*   Use `@MockitoBean` for ports in controller tests
*   Verify HTTP status + body structure (`$.data.*` and `$.errors[*].code`)
*   Test API versions (headers `Accept-Version`)

### Adapter Tests

#### HTTP Adapter (with WireMock)
For HTTP adapters, prefer WireMock to prove request/response mapping and status handling.

```java
@ExtendWith(MockitoExtension.class)
class ExternalServiceAdapterTest {

    // WireMock to simulate HTTP responses from the external service
    static WireMockServer wireMock = new WireMockServer(wireMockConfig().dynamicPort());

    @BeforeAll static void startWireMock() { wireMock.start(); }
    @AfterAll  static void stopWireMock()  { wireMock.stop(); }

    @Test
    void should_map_error_response_to_business_exception() {
        wireMock.stubFor(post(urlEqualTo("/transfer"))
            .willReturn(aResponse().withStatus(400)
                .withBody("{\"errorCode\": \"00021\"}")));

        StepVerifier.create(adapter.executeTransfer(buildCommand()))
            .expectError(BusinessException.class)
            .verify();
    }
}
```

#### GlobalExceptionHandler Adapter
```java
@WebFluxTest
@Import(GlobalExceptionHandler.class)
class GlobalExceptionHandlerTest {

    @Autowired private WebTestClient webTestClient;

    @Test
    void should_return_400_on_validation_error() {
        // POST with invalid body
        webTestClient.post().uri("/apply")
            .bodyValue("{}")  // incomplete body
            .exchange()
            .expectStatus().isBadRequest()
            .expectBody()
            .jsonPath("$.errors[0].code").isEqualTo("REQUEST_EXCEPTION");
    }
}
```

### MapStruct Mappers Tests
**Important:** After modifying a mapper, run `mvn clean` to regenerate the code before running tests.

```java
@Test
void should_map_request_dto_to_command() {
    TransferRequestDto dto = buildRequestDto();
    TransferCommand command = mapper.toCommand(dto, "token", "mobile");

    assertThat(command.originAccount()).isEqualTo(dto.originAccount());
    assertThat(command.channel()).isEqualTo("mobile");
    assertThat(command.amount()).isEqualByComparingTo(dto.amount());
}
```

### JaCoCo Configuration
Standard team exclusions (do not count towards coverage). Exclude only boilerplate packages, not business logic.

```xml
<!-- Root pom.xml or application/pom.xml -->
<configuration>
    <excludes>
        <exclude>**/config/**</exclude>
        <exclude>**/dto/**</exclude>
        <exclude>**/exception/**</exclude>
        <exclude>**/mapper/**</exclude>
        <exclude>**/model/**</exclude>
        <exclude>**/util/**</exclude>
        <exclude>**/*Application*</exclude>
    </excludes>
</configuration>
```

**Coverage Goal:** 100% on new use cases and adapters code; 80% overall minimum.

### Application Smoke Test
A minimal `@SpringBootTest` catches missing beans and broken configuration.

```java
@SpringBootTest
class MainApplicationTest {

    @Test
    void contextLoads() {
        // Verifies the Spring context starts without errors
    }
}
```

### Testing Anti-patterns

| Anti-pattern (❌) | Correction (✅) |
|---|---|
| `.block()` in reactive tests | Use `StepVerifier` |
| `Thread.sleep()` | Use `StepVerifier.withVirtualTime()` |
| Testing a concrete adapter implementation | Mock the OUT Port |
| No `@Import(GlobalExceptionHandler.class)` | Always import for controller tests |
| Not verifying error code in response | `.jsonPath("$.errors[0].code").isEqualTo(...)` |
| Changing a mapper without `mvn clean` | Run `mvn clean` before testing after mapper changes |
| Starting Spring for every use case test | Use Mockito + `StepVerifier` only |
| Excluding use cases from JaCoCo | Exclude only boilerplate packages |
