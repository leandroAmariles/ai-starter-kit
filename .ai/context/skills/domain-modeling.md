## What this pattern is
Domain modeling in this project requires strict object boundaries. Domain objects, entities, and DTOs MUST have explicitly defined attributes to ensure type safety and predictability.

This pattern explicitly forbids using dynamic generic maps or automated reflection-based mappers (like `ObjectMapper`, `JsonObject`, or `Map<String, Object>`) to hydrate domain objects. Allowing generic hydration breaks the compile-time contract and introduces runtime fragility.

## How to apply it

1.  **Define explicit attributes:** Ensure all your DTOs, Entities, and Domain Models declare every property explicitly with proper typing.
2.  **Use MapStruct for hydration:** Whenever data needs to be mapped across layers (e.g., from an inbound HTTP DTO to an internal Domain Object), you MUST use an explicitly defined MapStruct interface.
3.  **Prohibit dynamic conversion:** Never use `ObjectMapper.convertValue(source, Target.class)` or similar utility wrappers to bypass writing a mapper interface.

### ✅ Do: Use MapStruct for explicit hydration

```java
// Domain Object (explicit attributes)
public class UserProfile {
    private final String userId;
    private final String email;
    
    // constructor, getters...
}

// Inbound DTO
public class UserProfileDto {
    private String id;
    private String contactEmail;
    
    // getters, setters...
}

// Explicit Mapper layer
@Mapper(componentModel = "spring")
public interface UserProfileMapper {
    
    @Mapping(source = "id", target = "userId")
    @Mapping(source = "contactEmail", target = "email")
    UserProfile toDomain(UserProfileDto dto);
}
```

### ❌ Don't: Use dynamic mapping tools to hydrate domain objects

```java
// ❌ ANTI-PATTERN: Bypassing compile-time safety
public UserProfile toDomainBad(UserProfileDto dto) {
    // DO NOT DO THIS. If UserProfile attributes change, this fails silently at compile time.
    return objectMapper.convertValue(dto, UserProfile.class);
}

// ❌ ANTI-PATTERN: Hydrating via generic maps
public UserProfile fromMapBad(Map<String, Object> data) {
    // DO NOT DO THIS. Loss of type safety and contract integrity.
    return new UserProfile(
        (String) data.get("userId"),
        (String) data.get("email")
    );
}
```

## Rules by layer

*   **Adapters (Inbound):** Receive standard DTOs. Map them to Domain objects using MapStruct before passing to the use case.
*   **Domain (Use Cases):** Operate purely on Domain objects with explicit attributes. No knowledge of Jackson, Gson, or raw Maps.
*   **Adapters (Outbound):** Map Domain objects to external DTOs or Entities using MapStruct before interacting with external systems or DBs.
