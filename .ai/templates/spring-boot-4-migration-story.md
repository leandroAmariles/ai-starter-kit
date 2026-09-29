# Migracion Spring, Springboot

## Historia

**Como** equipo responsable del microservicio de {microservicio a migrar}
**quiero** migrar el reactor Maven de `bancadigital-ms-{microservicio a migrar}` al parent corporativo BAC 7 y a Spring Boot 4 con Spring Framework 7 y Jackson 3,  
**para** mantener el servicio en una plataforma Spring soportada, aprovechar la gestión corporativa de dependencias y reducir incompatibilidades y riesgos de seguridad, preservando el comportamiento funcional y los contratos actuales.

## Contexto y línea base

El repositorio es un reactor Maven multimódulo con módulos de dominio, aplicación, adaptadores REST y de eventos, integraciones externas y manejo de excepciones. La especificación corporativa aprobada se entrega mediante el POM de referencia BAC.

| Elemento | Línea base objetivo | Regla |
| --- | --- | --- |
| Parent de la aplicación | `com.bac.core:banca-digital-parent-pom:7.0.0-SNAPSHOT` | Heredar en el POM raíz del reactor; no copiar el contenido del parent a los módulos. |
| Spring Boot | `4.0.8`, administrado por el parent BAC indicado | Confirmar la versión efectiva con el POM efectivo. No declarar una versión independiente sin justificación. |
| Spring Framework | Versión administrada por el parent/BOM de Spring Boot 4 | No fijar una versión por separado. La versión observada anteriormente fue `7.0.9`; debe verificarse en el build final. |
| Java | `17` | Mantener compilación y APIs de Java 17, salvo justificación aprobada para una versión superior. |
| Spring Cloud | `2025.1.3`, según la propiedad del parent de referencia | Confirmar compatibilidad con el Boot heredado y resolución efectiva. |
| Jackson | Jackson 3 administrado por el parent; BOM de referencia `3.1.5` | Migrar APIs de aplicación. Investigar y justificar todo uso residual de Jackson 2. |

El POM de referencia también contiene versiones y overrides de seguridad, librerías BAC y plugins corporativos. Deben preservarse salvo incompatibilidad probada y aprobación de una alternativa equivalente.

## Alcance funcional y técnico

La migración abarca:

1. El parent del POM raíz y la alineación de POM de los módulos del reactor.
2. Dependencias directas, starters de producción y pruebas, plugins, annotation processors y propiedades afectadas por Boot 4.
3. Código Java de producción y pruebas que use APIs cambiadas o eliminadas.
4. Configuración Spring en YAML, properties y archivos de configuración adicionales identificados en el repositorio.
5. Integraciones JSON, HTTP, seguridad, eventos, persistencia y cualquier librería BAC cuya compatibilidad dependa de la versión de Spring o Jackson.
6. Pruebas de endpoints REST conforme a los criterios de negocio y contratos identificados para cada endpoint.
7. Validación modular y del reactor completo, incluidos los efectos de plugins heredados.

No se deben ejecutar despliegues, cambiar tráfico, modificar infraestructura remota ni ejecutar DDL contra bases de datos compartidas como parte de esta historia.

## Especificación de implementación

### Parent y gestión Maven

- Actualizar el POM raíz para heredar `com.bac.core:banca-digital-parent-pom:7.0.0-SNAPSHOT`.
- Mantener `<relativePath/>` para resolución corporativa remota, salvo que la estructura aprobada defina expresamente otra resolución local.
- Conservar el `packaging` propio del proyecto raíz y de cada módulo. El valor `pom` del parent corporativo no se copia a módulos de aplicación o librería.
- Eliminar propiedades y versiones redundantes solo después de confirmar que el parent las administra y que ningún plugin o módulo las consume.
- Comparar dependencias directas por módulo antes y después. Agregar un starter no autoriza a quitar una dependencia BAC adyacente o reemplazarla accidentalmente.
- Mantener las exclusiones transitivas únicamente cuando el árbol de dependencias identifique el artefacto conflictivo y se haya verificado que la exclusión no elimina APIs requeridas.

### Spring Boot 4 y Spring Framework 7

- Adoptar módulos y starters específicos de Boot 4 para las tecnologías utilizadas; actualizar nombres de starters obsoletos según la guía oficial.
- Revisar módulos de prueba específicos de Boot 4 y las anotaciones/autoconfiguraciones requeridas explícitamente por cada prueba.
- Eliminar usos de APIs deprecadas en la línea anterior cuando estén retiradas en Spring 7 o Boot 4.
- Revisar configuración de Spring Security y validar que autenticación, autorización, orden de filtros, CORS, CSRF y OAuth2 mantengan el mismo comportamiento.
- Revisar propiedades renombradas/eliminadas mediante la metadata oficial y, temporalmente si es necesario, el migrador de propiedades de Boot. Retirar el migrador después de corregir las propiedades.
- Revisar compatibilidad de Spring Cloud, Spring Data, Spring Security, Hibernate, Spring Batch, mensajería y librerías BAC usando versiones administradas y árboles efectivos, no solamente coordenadas declaradas.

### Jackson 3

- Usar las coordenadas y APIs de Jackson 3 gestionadas por el parent BAC. Migrar los paquetes que cambiaron a `tools.jackson`.
- Mantener `jackson-annotations` bajo `com.fasterxml.jackson.core` cuando corresponda a la distribución de Jackson 3.
- Migrar `ObjectMapper` de aplicación a `JsonMapper`/`XmlMapper` u otro mapper de formato apropiado cuando lo requiera la integración de Boot 4.
- Actualizar excepciones, constructores, customizers, módulos y opciones del mapper junto con imports, código y pruebas en un cambio coherente.
- Verificar explícitamente diferencias de defaults de Jackson 3 con pruebas de serialización/deserialización; no habilitar compatibilidad global sin evidencia.
- Identificar cada ruta efectiva que conserve `jackson-core` o `jackson-databind` 2.x. Documentar la dependencia que la introduce y clasificarla como necesaria o accidental. No añadir exclusiones hasta demostrar que no rompe a la librería consumidora.

### Configuración y compatibilidad

- Revisar `application.yml`, archivos properties, perfiles, bootstrap, configuración de seguridad, logging y descriptores de despliegue.
- Buscar referencias `javax.*` heredadas, APIs retiradas, configuración de Servlet incompatible y propiedades de Boot 3 que ya no apliquen.
- Mantener los overrides de CVE y seguridad del parent corporativo salvo que se pruebe que la versión administrada es equivalente o posterior y está corregida.
- No modificar el POM corporativo de referencia durante la migración del microservicio.

### Migración de librerías BAC

Como parte de esta historia se deben revisar todas las librerías BAC directas y transitivas utilizadas por el reactor que dependan de Spring Boot, Spring Framework, Spring Security, Jackson o APIs Jakarta. La lista siguiente contiene migraciones conocidas y debe usarse como referencia para comprobar su estado:

| Librería | PR de migración conocida |
| --- | --- |
| `bancadigital-lib-reactive-context-propagation` | [PR #8](https://github.com/BAC-Credomatic/bancadigital-lib-reactive-context-propagation/pull/8) |
| `bancadigital-lib-secure-crypto` | [PR #46](https://github.com/BAC-Credomatic/bancadigital-lib-secure-crypto/pull/46) |
| `bancadigital-lib-cache-manager` | [PR #33](https://github.com/BAC-Credomatic/bancadigital-lib-cache-manager/pull/33) |
| `bancadigital-lib-observability` | [PR #62](https://github.com/BAC-Credomatic/bancadigital-lib-observability/pull/62) |
| `bancadigital-lib-webclient` | [PR #18](https://github.com/BAC-Credomatic/bancadigital-lib-webclient/pull/18) |
| `bancadigital-lib-integration-data-power` | [PR #48](https://github.com/BAC-Credomatic/bancadigital-lib-integration-data-power/pull/48) |
| `bancadigital-lib-data-power-consolidated` | [PR #45](https://github.com/BAC-Credomatic/bancadigital-lib-data-power-consolidated/pull/45) |
| `bancadigital-lib-feature-flags` | [PR #121](https://github.com/BAC-Credomatic/bancadigital-lib-feature-flags/pull/121) |
| `banca-digital-parent-pom` | [PR #327](https://github.com/BAC-Credomatic/bancadigital-parent-pom/pull/327) |

Para cada librería consumida:

- Confirmar que el PR correspondiente esté integrado y publicado en una versión disponible para el build; la existencia del PR por sí sola no demuestra que la versión resuelta por el microservicio contenga la migración.
- Comparar la versión declarada/resuelta en el reactor con la versión migrada disponible. Actualizar la dependencia mediante el parent corporativo o la propiedad de versión correspondiente, sin fijar versiones ad hoc en módulos si el parent ya las administra.
- Revisar el árbol de dependencias y, cuando aplique, inspeccionar el código/metadata del artefacto para detectar referencias a Boot 3, Spring 6, Jackson 2 o `javax.*` incompatibles.
- Identificar toda librería BAC incompatible que no esté en la lista conocida. Registrar nombre, versión consumida, ruta directa/transitiva, incompatibilidad comprobada y equipo/repositorio propietario.
- Migrar las librerías pendientes antes de cerrar esta historia o crear historias de usuario vinculadas para los repositorios independientes. Una dependencia pendiente solo puede aceptarse como excepción si se documentan el impacto, la compatibilidad transitoria, el responsable y la fecha/criterio de resolución; no se deben ocultar incompatibilidades con exclusiones sin análisis.
- Cuando una librería se migre en otro repositorio, actualizar el microservicio a la versión publicada y ejecutar nuevamente las pruebas de los módulos consumidores.

### Pruebas de endpoints según criterios de negocio

- Inventariar los endpoints REST expuestos por los controladores y documentar para cada uno el método HTTP, la ruta, el propósito de negocio, el request, el response y los códigos HTTP esperados.
- Derivar los escenarios de prueba de los criterios de negocio existentes, las validaciones de entrada, las reglas de autorización y el comportamiento observable. No inventar reglas funcionales nuevas como parte de una migración técnica.
- Para cada endpoint, probar al menos un flujo exitoso representativo y los casos negativos relevantes: campos requeridos ausentes o inválidos, recursos inexistentes, reglas de negocio rechazadas y errores de dependencias cuando formen parte del contrato.
- Verificar que las respuestas mantengan estructura, códigos HTTP, headers relevantes, manejo de errores y compatibilidad JSON después del cambio a Spring Boot 4 y Jackson 3.
- Validar autenticación y autorización para endpoints protegidos, incluyendo acceso permitido y denegado según los roles o permisos definidos para el servicio.
- Usar pruebas de controlador o integración con el contexto Spring cuando se requiera validar routing, filtros, serialización y manejo global de excepciones. Usar mocks para aislar dependencias externas, no para sustituir la validación del contrato HTTP.
- Comparar los resultados con las pruebas y contratos previos a la migración. Toda diferencia debe corregirse o aprobarse explícitamente como cambio funcional separado.

## Criterios de aceptación

- [ ] El POM raíz hereda exactamente `com.bac.core:banca-digital-parent-pom:7.0.0-SNAPSHOT`.
- [ ] El parent efectivo y las versiones resueltas se confirman con el POM efectivo; Boot, Framework, Java, Spring Cloud y Jackson no se infieren únicamente de propiedades del JDK en ejecución.
- [ ] La compilación se mantiene en Java 17 y no requiere elevar el baseline sin decisión explícita.
- [ ] Todos los módulos mantienen su `groupId:artifactId:packaging` y las dependencias directas necesarias.
- [ ] Cada dependencia directa removida o reemplazada tiene justificación técnica documentada; no hay pérdidas accidentales ocultas por resolución transitiva.
- [ ] Todas las librerías BAC directas y transitivas relevantes están inventariadas con versión resuelta, estado de migración y evidencia.
- [ ] Las librerías de la lista conocida están verificadas contra sus PRs y versiones publicadas, y el reactor consume una versión que contiene efectivamente la migración.
- [ ] Cada librería BAC incompatible fuera de la lista se migró y publicó, o tiene una historia vinculada de excepción aprobada con responsable, impacto y criterio de cierre.
- [ ] Las versiones migradas de las librerías BAC se validaron mediante el árbol efectivo y pruebas de los módulos consumidores.
- [ ] Las dependencias y APIs JSON utilizadas por código de aplicación están migradas a Jackson 3 donde exista una ruta compatible.
- [ ] Los usos restantes de Jackson 2 están identificados con su ruta transitiva, módulo afectado y motivo de retención.
- [ ] Las propiedades, starters, imports, plugins y APIs retiradas de Boot 3/Spring 6 relevantes para el proyecto se han migrado.
- [ ] Las pruebas de serialización, deserialización, errores y defaults relevantes pasan con Jackson 3.
- [ ] Cada endpoint REST identificado tiene escenarios de prueba trazables a sus criterios de negocio y contrato HTTP vigentes.
- [ ] Los escenarios exitosos y negativos verifican request, response, códigos HTTP, validaciones, autorización y errores aplicables por endpoint.
- [ ] Las pruebas de regresión confirman que la migración no cambia inadvertidamente contratos REST ni reglas de negocio.
- [ ] Las pruebas unitarias y de integración de los módulos afectados pasan.
- [ ] El build de pruebas del reactor Maven completo termina con código de salida exitoso.
- [ ] El árbol efectivo no contiene versiones incompatibles o duplicadas de Spring ni dependencias legacy no justificadas.
- [ ] `git diff --check` no reporta errores de whitespace o marcadores de conflicto.
- [ ] Los archivos generados por plugins durante la validación se distinguen de los cambios intencionales y no se incluyen accidentalmente.
- [ ] No se ejecutaron despliegues, cambios de tráfico ni operaciones contra bases de datos compartidas.

## Validación Sugerida

Desde la raíz del reactor, usar Maven Wrapper cuando exista; de lo contrario, `mvn`. Adaptar perfiles y comandos a la estructura real del proyecto.

```text
./mvnw -N help:effective-pom -Doutput=target/effective-pom.xml
./mvnw dependency:tree '-Dincludes=org.springframework,org.springframework.boot,com.fasterxml.jackson.*,tools.jackson.*'
./mvnw -DskipTests compile
./mvnw test
./mvnw verify
git diff --check
```

En Windows, usar `mvnw.cmd` si está disponible. En PowerShell, citar filtros con comodines para impedir su expansión por el shell. `verify` debe ejecutarse solo si sus plugins asociados son seguros en entorno local; omitir análisis/publicación/remediación remota cuando corresponda y registrar cada omisión.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
| --- | --- |
| Parent corporativo o Spring Cloud no resuelve/compatible | Validar parent efectivo y release train antes de cambios masivos; detenerse y reportar si hay incompatibilidad. |
| Dependencias BAC aún requieren Jackson 2 o Spring anterior | Localizar la ruta con `dependency:tree`, actualizar librería o justificar compatibilidad aislada; no excluir a ciegas. |
| Cambio de default de Jackson altera contratos | Pruebas con casos reales de payload, nulos, fechas, duración y campos desconocidos. |
| Starter nuevo sustituye por error una dependencia directa | Comparación automática/manual de coordenadas por módulo antes y después. |
| Cambio de propiedades altera configuración por ambiente | Comparar todos los perfiles y validar binding con configuración de prueba sin credenciales reales. |
| Plugins corporativos generan archivos durante Maven | Guardar estado inicial de Git y comparar al final; separar artefactos generados de cambios de producto. |
| Migración de esquema requerida | Crear migración versionada revisable; no ejecutar DDL en ambientes compartidos durante esta historia. |

## Fuera de alcance

- Despliegue a staging o producción.
- Cambios de tráfico, feature flags operacionales o rollback en infraestructura.
- Ejecución de DDL sobre bases compartidas.
- Cambios funcionales no necesarios para la compatibilidad con la plataforma objetivo.
- Eliminación de dependencias transitivas sin análisis de consumidores.

