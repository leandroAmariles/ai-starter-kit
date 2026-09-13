# Style and Practices Guidelines

Canonical consolidation of architectural decisions, patterns, and development rules for this project's Java/Spring microservices. This serves as the mandatory baseline reference for all features developed across the codebase.

> Illustrative examples below use a generic `Order`/`Transfer`/`Account` domain and a `<SERVICE>` placeholder for your service's name — replace them with your own domain and naming as needed.

---

## 1. Naming Conventions (English Mandatory)

All identifiers (classes, methods, variables, constants, fields) MUST be in **English**.

| Spanish (❌) | English (✅) |
|---|---|
| `ObtenerEstadoCuentaCommand` | `GetAccountStatementCommand` |
| `ObtenerEstadoCuentaResponse` | `GetAccountStatementResponse` |
| `ObtenerEstadoCuentaServicePort` | `GetAccountStatementServicePort` |
| `CONSERVADOR` | `CONSERVATIVE` |
| `MODERADO` | `MODERATE` |
| `AGRESIVO` | `AGGRESSIVE` |
| `fetchEstadoCuenta()` | `fetchAccountStatement()` |

---

## 2. Constants and Enums (`domain/model`)

Domain constants and business enums must live in `domain/model`, not scattered within use cases.

### 2.1 Constants Class (`model/constants/`)
Use Lombok's `@UtilityClass` with grouped inner classes by context:

```java
@UtilityClass
public class GeneralConstants {

    @UtilityClass
    public class DateFormat {
        public static final String DATE_DP_FORMAT      = "yyyyMMdd";
        public static final String DATE_ISO_FORMAT     = "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'";
        public static final String DATE_DP_DASH_FORMAT = "yyyy-MM-dd";
    }

    @UtilityClass
    public class Concurrency {
        public static final int FLATMAP_CONCURRENCY = 5;
    }
}
```

### 2.2 Business Enums (`model/enums/`)
When an external value uses different terminology from the domain, create an enum with a conversion method:

```java
@Getter
@RequiredArgsConstructor
public enum ClientProfile {
    CONSERVATIVE("CONSERVADOR"),
    MODERATE("MODERADO"),
    AGGRESSIVE("AGRESIVO");

    private final String externalValue;

    public static String fromExternalValue(String externalValue) {
        if (externalValue == null) return null;
        for (ClientProfile p : values()) {
            if (p.externalValue.equalsIgnoreCase(externalValue)) return p.name();
        }
        return externalValue; // fallback with warning log in the use case
    }
}
```

---

## 3. PMD and Checkstyle Rules

| Rule | Description | Fix |
|---|---|---|
| `UnnecessaryImport` | Unused import | Remove the import |
| `UnusedFormalParameter` | Unused method parameter | Use it or refactor signature |
| `NeedBraces` | `if/for` blocks without braces | Always use `{ }` |
| Max line length: 121 chars | Line too long | Split into multiple lines |

---

## 4. Test Coverage (JaCoCo — 80% minimum)

### 4.1 Configured Exclusions
The following packages are excluded from coverage calculations and should only contain logic-less code:
- `**/dto/**`
- `**/config/**`
- `**/model/**`
- `**/util/mapper/**`
- `**/exception/**`

### 4.2 Integration Tests with WireMock (`@MockitoSettings(strictness = LENIENT)`)
When a `@BeforeEach` registers stubs that not all tests use, use `@MockitoSettings(strictness = Strictness.LENIENT)` on the class to prevent `UnnecessaryStubbingException`.

```java
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class GenericIntegrationTest extends IntegrationTestBase { ... }
```

---

## 5. Commits (Conventional Commits)

Mandatory format:
```
type(scope): description in english
```

> If your organization or AI agent requires a co-author trailer (e.g. `Co-authored-by: <agent> <email>`), add that convention in the agent-specific rules for that tool rather than here, so it doesn't leak into every agent's generated instructions.

| Type | When to use it |
|---|---|
| `feat` | New functionality |
| `fix` | Bug fix |
| `refactor` | Code restructuring without adding/fixing logic |
| `chore` | Configuration, dependencies, CI |
| `docs` | Documentation only |
| `test` | Tests only |

---

## 6. Exception Handling

### 6.1 Structure
The project has an exception hierarchy in `helper/exception/` and a centralized handler in `infrastructure/in/rest/handler/GlobalExceptionHandler`. 
**Rule:** Throw typed exceptions in any layer and let them bubble up to the handler. Never build error responses (e.g. `ResponseEntity`) inside adapters or use cases.

### 6.2 General Rules
- **Never** catch an exception just to return a `ResponseEntity` inside an adapter or use case.
- **Always** use `ExceptionUtil` (or the project's equivalent) to build exceptions with standardized codes and descriptions.
- **Error codes** live in `ResponseCodeEnum` — format `<SERVICE>_XXXX_NNNNN` (define your own service prefix).
- The `GlobalExceptionHandler` is the **only place** where exceptions are mapped to HTTP responses.

---

## 7. Feature Checklist

Before opening a PR, verify:

- [ ] All identifiers are in English (classes, methods, variables, fields)
- [ ] Controller has no logic — only builds command and calls the Inbound Port
- [ ] Adapters resolve external dependencies (e.g. Security) and build objects with explicit mappers
- [ ] UseCase has no infrastructure or network dependencies
- [ ] Domain constants in `model/constants/` using `@UtilityClass`
- [ ] External values mapped with enums in `model/enums/`
- [ ] Typed exceptions in `helper/exception/`, codes in `ResponseCodeEnum`, handled in `GlobalExceptionHandler`
- [ ] Local build passes: `mvn install --no-transfer-progress -o -Dskip.srcclr=true`
- [ ] Code coverage ≥ 80% on modified modules
- [ ] No PMD or Checkstyle violations
- [ ] Commits follow Conventional Commits format

---

## 8. Pre-Commit Checklist

Execute **before every commit**:

### 8.1 Tests
Run tests for affected modules:
```bash
mvn test -pl <changed-module> -am -Dskip.srcclr=true --no-transfer-progress
```

### 8.2 Checkstyle
Validate style rules before committing to avoid pipeline rejections:
```bash
mvn checkstyle:check -Dskip.srcclr=true --no-transfer-progress
```

### 8.3 Coverage (JaCoCo)
Verify coverage threshold remains ≥ 80%:
```bash
mvn verify -Dskip.srcclr=true -Dcheckstyle.skip=true --no-transfer-progress
```

### 8.4 Junk / Temporary Files
Before `git add`, review for loose files:
```bash
git status --short
```
Remove:
- `*.orig`, `*.rej`, `*.bak`, `*.swp`
- `target/`, `.idea/`, `*.iml` (should be in `.gitignore`)
- `*.log`, `dumps/`
- Scripts/payloads in `/tmp/`
- Test files generated during debug (`test.json`, `output.txt`)

### 8.5 Diff Review
Review the full diff before committing:
```bash
git diff --staged
```
Verify that **only** intentional feature changes are present (no massive formatting changes, auto-reorganized imports, or accidentally touched files).

### 8.6 Atomic Commits
One commit = one logical change. Use `git add -p` to stage by hunks if multiple changes were made.
