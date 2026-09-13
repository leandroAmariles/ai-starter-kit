# Error Translation — Context Skill

## What this pattern is
Error translation standardizes how technical and business failures become HTTP responses. The model uses **two exception hierarchies** and one shared response envelope:

*   `BusinessException` → client or business problems → 4xx
*   `TechnicalException` → infrastructure or unexpected system problems → 5xx

Every error must resolve through a central `ErrorCode` enum and be returned inside a standard envelope `ResponseDto<T>` with `ErrorDto` entries.

## How to apply it

### 1. Define a shared `ErrorCode` enum
Each code contains: `code`, `description`, and `HttpStatus`.

The standard format is `<SERVICE_PREFIX>_<SUBSYSTEM>_<NNNNN>`:

| Subsystem | Meaning |
|---|---|
| `GE` | General — generic service errors (e.g., `<SERVICE>_GE_NNNNN`) |
| `EXT` | External system integration (e.g., `<SERVICE>_EXT_NNNNN`) |
| `DB` | Database — persistence layer (e.g., `<SERVICE>_DB_NNNNN`) |
| `AUTH` | Authorization (e.g., `<SERVICE>_AUTH_NNNNN`) |

**Shared cross-service codes:**
*   `AUTH_ROLE_00001`: authorization failures (Role not allowed)
*   `CIPHER_GE_001`: crypto failures (`SecureCrypto`)

```java
@Getter
@RequiredArgsConstructor
public enum ErrorCode {
    INVALID_REQUEST("<SERVICE>_GE_00001", "Invalid request", HttpStatus.BAD_REQUEST),
    CUSTOMER_NOT_FOUND("<SERVICE>_GE_00002", "Customer not found", HttpStatus.NOT_FOUND),
    EXTERNAL_SERVICE_FAILURE("<SERVICE>_EXT_00001", "Provider integration error", HttpStatus.BAD_GATEWAY),
    DATABASE_FAILURE("<SERVICE>_DB_00001", "Database operation failed", HttpStatus.INTERNAL_SERVER_ERROR),
    FORBIDDEN_ROLE("<SERVICE>_AUTH_00001", "Role not allowed", HttpStatus.FORBIDDEN),
    CRYPTO_FAILURE("<SERVICE>_GE_00003", "Crypto operation failed", HttpStatus.INTERNAL_SERVER_ERROR),
    UNKNOWN_ERROR("<SERVICE>_GE_99999", "Unexpected internal error", HttpStatus.INTERNAL_SERVER_ERROR);

    private final String code;
    private final String description;
    private final HttpStatus httpStatus;
}
```

### 2. Implement the two exception hierarchies

```java
// BusinessException — business error, usually 4xx
@Getter
public class BusinessException extends RuntimeException {
    private final ErrorCode errorCode;

    public BusinessException(ErrorCode errorCode) {
        super(errorCode.getDescription());
        this.errorCode = errorCode;
    }

    public BusinessException(ErrorCode errorCode, Throwable cause) {
        super(errorCode.getDescription(), cause);
        this.errorCode = errorCode;
    }
}

// TechnicalException — infrastructure error, usually 5xx
@Getter
public class TechnicalException extends RuntimeException {
    private final ErrorCode errorCode;

    public TechnicalException(ErrorCode errorCode) {
        super(errorCode.getDescription());
        this.errorCode = errorCode;
    }

    public TechnicalException(ErrorCode errorCode, Throwable cause) {
        super(errorCode.getDescription(), cause);
        this.errorCode = errorCode;
    }
}
```
*Rule of thumb:*
*   validation, business rule, permission, not-found → `BusinessException`
*   timeout, parsing, network, database, unknown → `TechnicalException`

### 3. Return all API errors through `ResponseDto<T>` + `ErrorDto`

```java
@Builder
public record ErrorDto(
        String code,
        String description,
        Map<String, String> attributes) {
}

@Builder
public record ResponseDto<T>(
        T data,
        List<ErrorDto> errors) {

    public static <T> ResponseDto<T> success(T data) {
        return new ResponseDto<>(data, List.of());
    }

    public static <T> ResponseDto<T> failure(List<ErrorDto> errors) {
        return new ResponseDto<>(null, errors);
    }
}
```

### 4. Centralize response building in `GlobalExceptionHandler`
Required handlers in `infrastructure/in/rest/.../handler/GlobalExceptionHandler.java`:
*   `WebExchangeBindException` (Bean Validation)
*   `HandlerMethodValidationException` (@Validated in parameters)
*   `BusinessException`
*   `TechnicalException`
*   `RoleNotAllowedException`
*   `SecureCryptoException`
*   `Throwable` fallback

```java
@RestControllerAdvice
public class GlobalExceptionHandler {

    private final SecureLogger log = new SecureLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(WebExchangeBindException.class)
    public Mono<ResponseEntity<ResponseDto<Object>>> handleBind(WebExchangeBindException ex) {
        Map<String, String> attributes = ex.getFieldErrors().stream()
            .collect(Collectors.toMap(FieldError::getField, DefaultMessageSourceResolvable::getDefaultMessage,
                (left, right) -> right));

        ErrorDto error = ErrorDto.builder()
            .code(ErrorCode.INVALID_REQUEST.getCode())
            .description(ErrorCode.INVALID_REQUEST.getDescription())
            .attributes(attributes)
            .build();

        return Mono.just(ResponseEntity.status(ErrorCode.INVALID_REQUEST.getHttpStatus())
            .body(ResponseDto.failure(List.of(error))));
    }

    @ExceptionHandler(BusinessException.class)
    public Mono<ResponseEntity<ResponseDto<Object>>> handleBusiness(BusinessException ex) {
        log.error("Business error: code={}", ex.getErrorCode().getCode(), ex);
        return buildResponse(ex.getErrorCode());
    }

    @ExceptionHandler(TechnicalException.class)
    public Mono<ResponseEntity<ResponseDto<Object>>> handleTechnical(TechnicalException ex) {
        log.error("Technical error: code={}", ex.getErrorCode().getCode(), ex);
        return buildResponse(ex.getErrorCode());
    }

    @ExceptionHandler(RoleNotAllowedException.class)
    public Mono<ResponseEntity<ResponseDto<Object>>> handleRole(RoleNotAllowedException ex) {
        return buildResponse(ErrorCode.FORBIDDEN_ROLE);
    }

    @ExceptionHandler(SecureCryptoException.class)
    public Mono<ResponseEntity<ResponseDto<Object>>> handleCrypto(SecureCryptoException ex) {
        log.error("Crypto error", ex);
        return buildResponse(ErrorCode.CRYPTO_FAILURE);
    }

    @ExceptionHandler(Throwable.class)
    public Mono<ResponseEntity<ResponseDto<Object>>> handleFallback(Throwable ex) {
        log.error("Unexpected error", ex);
        return buildResponse(ErrorCode.UNKNOWN_ERROR);
    }

    private Mono<ResponseEntity<ResponseDto<Object>>> buildResponse(ErrorCode errorCode) {
        ErrorDto errorDto = ErrorDto.builder()
            .code(errorCode.getCode())
            .description(errorCode.getDescription())
            .build();
        return Mono.just(ResponseEntity.status(errorCode.getHttpStatus())
            .body(ResponseDto.failure(List.of(errorDto))));
    }
}
```

### 5. Translate infrastructure failures before they reach the handler
Adapters and services should wrap low-level exceptions with `BusinessException` or `TechnicalException`.

```java
return providerClient.execute(request)
    .onErrorMap(WebClientResponseException.class,
        error -> new TechnicalException(ErrorCode.EXTERNAL_SERVICE_FAILURE, error));
```

### How to add a new exception
1. Add a new code to `ErrorCode`
2. Choose the correct hierarchy (`BusinessException` or `TechnicalException`) and optionally create a specific class if needed.
3. Throw or map it where the failure occurs using `.onErrorMap` or explicitly returning `Mono.error(..)`.
4. Add a dedicated handler in `GlobalExceptionHandler` ONLY if behavior differs from the generic business/technical handlers (otherwise, no new handler is needed). Add a test in `GlobalExceptionHandlerTest`.

### Anti-patterns to avoid

| Anti-pattern (❌) | Correction (✅) |
|---|---|
| Throwing plain `RuntimeException` from business code | Throw `BusinessException` or `TechnicalException` |
| Returning empty DTO when an external call fails | Propagate with `onErrorMap` to `BusinessException` |
| Hardcoding HTTP status in multiple controllers | Centralize in `ErrorCode` + handler |
| Returning raw exception message or stacktrace to clients | Return `ErrorDto` from known `ErrorCode` (only `code` + `description`) |
| Mixing business and technical failures in one base class | Keep two hierarchies: 4xx and 5xx |
| `GlobalExceptionHandler` without `Throwable` fallback | Always add `Throwable` fallback at the end |
| Handler for `Throwable` before specific ones | `Throwable` always at the end |
| Validation errors without attributes map | Populate `ErrorDto.attributes` |
| Using project-specific prefixes in shared docs | Use `<SERVICE>` placeholders |
| Special-casing every exception unnecessarily | Reuse generic handlers unless response must change |
