package com.globant.bac.backend;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.body.CallableDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.EnumDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.RecordDeclaration;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.MethodCallExpr;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;
import org.xml.sax.SAXException;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.parsers.ParserConfigurationException;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

final class MigrationContextWriter {

    private static final int MAX_TOTAL_CHARACTERS = 1_000_000;
    private static final Pattern SENSITIVE_ASSIGNMENT = Pattern.compile(
            "(?i)^(\\s*(?:[\\w.-]+\\s+)*[\\w.-]*(?:password|passwd|secret|token|api[-_.]?key|credential|private[-_.]?key)[\\w.-]*\\s*[:=]\\s*).*$"
    );
    private static final Pattern SENSITIVE_XML_ELEMENT = Pattern.compile(
            "(?i)^(\\s*<([\\w.-]*(?:password|passwd|secret|token|api[-_.]?key|credential|private[-_.]?key)[\\w.-]*)>).*?(</\\2>\\s*)$"
    );
    private static final Map<String, Pattern> MIGRATION_PATTERNS = migrationPatterns();
    private static final Set<String> MIGRATION_METHODS = Set.of(
            "readValue", "writeValue", "registerModule", "findAndRegisterModules", "configure", "enable", "disable",
            "antMatchers", "requestMatchers", "cors", "csrf", "and"
    );

    CodebaseCrawler.ContextResult write(
            Path rootPath,
            CodebaseCrawler.CrawlResult crawlResult,
            Path outputPath
    ) throws IOException {
        Path root = rootPath.toAbsolutePath().normalize();
        Path output = outputPath.toAbsolutePath().normalize();
        Instant generatedAt = Instant.now();
        List<Path> parseFailures = new ArrayList<>();
        List<ParseFailure> parseErrors = new ArrayList<>();
        List<Finding> findings = new ArrayList<>();
        List<FileMetadata> fileMetadata = new ArrayList<>();
        List<String> productionComponents = new ArrayList<>();
        List<String> testComponents = new ArrayList<>();
        int includedFiles = 0;

        String configurations = buildConfigurations(
            root, crawlResult.configFiles(), findings, fileMetadata, parseFailures, parseErrors);
        includedFiles += crawlResult.configFiles().size();

        for (Path javaFile : crawlResult.javaSourceFiles()) {
            String relativePath = relativePath(root, javaFile);
            boolean testSource = isTestSource(relativePath);
            try {
                String source = Files.readString(javaFile, StandardCharsets.UTF_8);
                fileMetadata.add(new FileMetadata(relativePath, testSource ? "test" : "main", sha256(source)));
                collectFindings(relativePath, source, findings);
                String component = parseJavaSource(javaFile, relativePath, testSource);
                if (!component.isBlank()) {
                    (testSource ? testComponents : productionComponents).add(component);
                    includedFiles++;
                }
            } catch (Exception exception) {
                parseFailures.add(javaFile);
                parseErrors.add(new ParseFailure(relativePath, conciseMessage(exception)));
            }
        }

        String mavenModel = buildMavenModel(root, crawlResult.configFiles());
        String productionXml = wrap("production_components", productionComponents);
        String testXml = wrap("test_components", testComponents);
        String componentsXml = "  <components>\n" + productionXml + testXml + "  </components>\n";
        String findingsXml = buildFindings(findings);
        String errorsXml = buildParseErrors(parseErrors);
        String manifestXml = buildManifest(root, generatedAt, crawlResult, fileMetadata, parseErrors);

        List<Section> sections = List.of(
                new Section("manifest", manifestXml),
                new Section("maven_model", mavenModel),
                new Section("configurations", configurations),
                new Section("components", componentsXml),
                new Section("migration_findings", findingsXml),
                new Section("parse_errors", errorsXml)
        );

        int omittedFiles = 0;
        int truncatedFiles = 0;
        StringBuilder primary = new StringBuilder();
        primary.append("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
        primary.append("<codebase_context root=\"").append(escapeXml(root.toString()))
                .append("\" generated_at=\"").append(generatedAt).append("\" schema_version=\"2\">\n");
        for (Section section : sections) {
            if (primary.length() + section.xml().length() + 32 > MAX_TOTAL_CHARACTERS) {
                omittedFiles += countFileElements(section.xml());
                truncatedFiles++;
                primary.append("  <omitted_section name=\"").append(section.name())
                        .append("\" reason=\"total-size-limit\"/>\n");
                continue;
            }
            primary.append(section.xml());
        }
        primary.append("</codebase_context>\n");

        Path parent = output.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        Files.writeString(output, primary.toString(), StandardCharsets.UTF_8);
        List<Section> companionSections = new ArrayList<>(sections);
        companionSections.removeIf(section -> section.name().equals("components"));
        companionSections.add(new Section("production_code", productionXml));
        companionSections.add(new Section("tests", testXml));
        writeCompanionArtifacts(output, root, generatedAt, companionSections);

        return new CodebaseCrawler.ContextResult(
                output,
                includedFiles,
                truncatedFiles,
                omittedFiles,
                List.copyOf(parseFailures)
        );
    }

    private String buildConfigurations(
            Path root,
            List<Path> configFiles,
            List<Finding> findings,
            List<FileMetadata> metadata,
            List<Path> unreadableFiles,
            List<ParseFailure> errors
    ) {
        StringBuilder xml = new StringBuilder("  <configurations>\n");
        for (Path configFile : configFiles) {
            String relativePath = relativePath(root, configFile);
            try {
                String content = Files.readString(configFile, StandardCharsets.UTF_8);
                metadata.add(new FileMetadata(relativePath, "configuration", sha256(content)));
                collectFindings(relativePath, content, findings);
                xml.append("    <config_file path=\"").append(escapeXml(relativePath)).append("\">\n")
                        .append("      <![CDATA[\n").append(cdata(redactSensitiveValues(content)))
                        .append("\n      ]]>\n    </config_file>\n");
            } catch (IOException exception) {
                unreadableFiles.add(configFile);
                errors.add(new ParseFailure(relativePath, "configuration-read: " + conciseMessage(exception)));
                xml.append("    <config_error path=\"").append(escapeXml(relativePath))
                        .append("\" message=\"").append(escapeXml(conciseMessage(exception))).append("\"/>\n");
            }
        }
        return xml.append("  </configurations>\n").toString();
    }

    private String parseJavaSource(Path file, String relativePath, boolean testSource) throws IOException {
        CompilationUnit unit = StaticJavaParser.parse(file);
        String packageName = unit.getPackageDeclaration().map(declaration -> declaration.getNameAsString()).orElse("");
        StringBuilder xml = new StringBuilder();
        xml.append("      <source_file path=\"").append(escapeXml(relativePath))
                .append("\" scope=\"").append(testSource ? "test" : "main").append("\">\n");
        xml.append("        <imports>\n");
        for (ImportDeclaration importDeclaration : unit.getImports()) {
            xml.append("          <import name=\"").append(escapeXml(importDeclaration.getNameAsString()))
                    .append("\" static=\"").append(importDeclaration.isStatic())
                    .append("\" wildcard=\"").append(importDeclaration.isAsterisk()).append("\"/>\n");
        }
        xml.append("        </imports>\n");

        unit.findAll(ClassOrInterfaceDeclaration.class).forEach(type -> appendClass(xml, type, packageName));
        unit.findAll(EnumDeclaration.class).forEach(type -> appendEnum(xml, type, packageName));
        unit.findAll(RecordDeclaration.class).forEach(type -> appendRecord(xml, type, packageName));
        xml.append("      </source_file>\n");
        return xml.toString();
    }

    private void appendClass(StringBuilder xml, ClassOrInterfaceDeclaration type, String packageName) {
        xml.append("        <class name=\"").append(escapeXml(type.getNameAsString()))
                .append("\" package=\"").append(escapeXml(packageName))
                .append("\" role=\"").append(determineClassRole(type)).append("\"")
                .append(" interface=\"").append(type.isInterface()).append("\"")
                .append(" extends=\"").append(escapeXml(type.getExtendedTypes().toString())).append("\"")
                .append(" implements=\"").append(escapeXml(type.getImplementedTypes().toString())).append("\">\n");
        appendAnnotations(xml, type.getAnnotations(), "          ");
        xml.append("          <fields>\n");
        for (FieldDeclaration field : type.getFields()) {
            String annotations = annotationNames(field.getAnnotations());
            field.getVariables().forEach(variable -> xml.append("            <field name=\"")
                    .append(escapeXml(variable.getNameAsString())).append("\" type=\"")
                    .append(escapeXml(variable.getTypeAsString())).append("\" visibility=\"")
                    .append(visibility(field)).append("\" annotations=\"").append(escapeXml(annotations))
                    .append("\" has_initializer=\"").append(variable.getInitializer().isPresent()).append("\"/>\n"));
        }
        xml.append("          </fields>\n          <constructors>\n");
        for (ConstructorDeclaration constructor : type.getConstructors()) {
            appendCallable(xml, constructor, "constructor", "            ");
        }
        xml.append("          </constructors>\n          <methods>\n");
        for (MethodDeclaration method : type.getMethods()) {
            appendCallable(xml, method, "method", "            ");
        }
        xml.append("          </methods>\n          <migration_calls>\n");
        type.findAll(MethodCallExpr.class).stream()
                .filter(call -> MIGRATION_METHODS.contains(call.getNameAsString()))
                .map(call -> call.getNameAsString() + "@" + call.getRange().map(range -> range.begin.line).orElse(-1))
                .distinct()
                .forEach(call -> xml.append("            <call value=\"").append(escapeXml(call)).append("\"/>\n"));
        xml.append("          </migration_calls>\n        </class>\n");
    }

    private void appendCallable(StringBuilder xml, CallableDeclaration<?> callable, String element, String indent) {
        String returnType = callable instanceof MethodDeclaration method ? method.getTypeAsString() : "";
        String parameters = callable.getParameters().stream()
                .map(parameter -> parameter.getTypeAsString() + " " + parameter.getNameAsString())
                .collect(Collectors.joining(", "));
        xml.append(indent).append("<").append(element).append(" name=\"")
                .append(escapeXml(callable.getNameAsString())).append("\" return_type=\"")
                .append(escapeXml(returnType)).append("\" parameters=\"")
                .append(escapeXml(parameters)).append("\" visibility=\"")
                .append(visibility(callable)).append("\" annotations=\"")
                .append(escapeXml(annotationNames(callable.getAnnotations()))).append("\"/>\n");
    }

    private void appendEnum(StringBuilder xml, EnumDeclaration type, String packageName) {
        xml.append("        <enum name=\"").append(escapeXml(type.getNameAsString()))
                .append("\" package=\"").append(escapeXml(packageName)).append("\">\n");
        type.getEntries().forEach(entry -> xml.append("          <constant name=\"")
                .append(escapeXml(entry.getNameAsString())).append("\"/>\n"));
        xml.append("        </enum>\n");
    }

    private void appendRecord(StringBuilder xml, RecordDeclaration type, String packageName) {
        xml.append("        <record name=\"").append(escapeXml(type.getNameAsString()))
                .append("\" package=\"").append(escapeXml(packageName)).append("\">\n");
        type.getParameters().forEach(parameter -> xml.append("          <component name=\"")
                .append(escapeXml(parameter.getNameAsString())).append("\" type=\"")
                .append(escapeXml(parameter.getTypeAsString())).append("\"/>\n"));
        xml.append("        </record>\n");
    }

    private String buildMavenModel(Path root, List<Path> configFiles) {
        StringBuilder xml = new StringBuilder("  <maven_model>\n");
        configFiles.stream()
                .filter(path -> path.getFileName().toString().equalsIgnoreCase("pom.xml"))
                .forEach(path -> appendPomModel(xml, root, path));
        return xml.append("  </maven_model>\n").toString();
    }

    private void appendPomModel(StringBuilder xml, Path root, Path pom) {
        String relativePath = relativePath(root, pom);
        try (InputStream input = Files.newInputStream(pom)) {
            DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            factory.setFeature("http://xml.org/sax/features/external-general-entities", false);
            factory.setFeature("http://xml.org/sax/features/external-parameter-entities", false);
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
            factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
            Document document = factory.newDocumentBuilder().parse(input);
            Element project = document.getDocumentElement();
            xml.append("    <module pom=\"").append(escapeXml(relativePath)).append("\" group_id=\"")
                    .append(escapeXml(value(project, "groupId"))).append("\" artifact_id=\"")
                    .append(escapeXml(value(project, "artifactId"))).append("\" version=\"")
                    .append(escapeXml(value(project, "version"))).append("\" packaging=\"")
                    .append(escapeXml(value(project, "packaging"))).append("\">\n");
            Element parent = child(project, "parent");
            if (parent != null) {
                xml.append("      <parent group_id=\"").append(escapeXml(value(parent, "groupId")))
                        .append("\" artifact_id=\"").append(escapeXml(value(parent, "artifactId")))
                        .append("\" version=\"").append(escapeXml(value(parent, "version"))).append("\"/>\n");
            }
            appendCoordinates(xml, child(project, "dependencies"), "dependency", "dependencies", "        ");
            Element dependencyManagement = child(project, "dependencyManagement");
            appendCoordinates(xml, dependencyManagement == null ? null : child(dependencyManagement, "dependencies"),
                    "dependency", "managed_dependencies", "        ");
            Element build = child(project, "build");
            appendCoordinates(xml, build == null ? null : child(build, "plugins"), "plugin", "plugins", "        ");
            xml.append("    </module>\n");
        } catch (IOException | ParserConfigurationException | SAXException exception) {
            xml.append("    <maven_error pom=\"").append(escapeXml(relativePath)).append("\" message=\"")
                    .append(escapeXml(conciseMessage(exception))).append("\"/>\n");
        }
    }

    private void appendCoordinates(
            StringBuilder xml,
            Element container,
            String itemName,
            String wrapperName,
            String indent
    ) {
        xml.append(indent).append("<").append(wrapperName).append(">\n");
        if (container != null) {
            for (Element item : children(container, itemName)) {
                xml.append(indent).append("  <coordinate group_id=\"").append(escapeXml(value(item, "groupId")))
                        .append("\" artifact_id=\"").append(escapeXml(value(item, "artifactId")))
                        .append("\" version=\"").append(escapeXml(value(item, "version")))
                        .append("\" scope=\"").append(escapeXml(value(item, "scope"))).append("\"/>\n");
            }
        }
        xml.append(indent).append("</").append(wrapperName).append(">\n");
    }

    private String buildManifest(
            Path root,
            Instant generatedAt,
            CodebaseCrawler.CrawlResult crawlResult,
            List<FileMetadata> metadata,
            List<ParseFailure> parseErrors
    ) {
        StringBuilder xml = new StringBuilder("  <manifest root=\"").append(escapeXml(root.toString()))
                .append("\" generated_at=\"").append(generatedAt).append("\" git_branch=\"")
                .append(escapeXml(gitValue(root, "rev-parse", "--abbrev-ref", "HEAD"))).append("\" git_commit=\"")
                .append(escapeXml(gitValue(root, "rev-parse", "HEAD"))).append("\" java_files=\"")
                .append(crawlResult.javaSourceFiles().size()).append("\" config_files=\"")
                .append(crawlResult.configFiles().size()).append("\" parse_errors=\"")
                .append(parseErrors.size()).append("\">\n");
        metadata.stream().sorted(Comparator.comparing(FileMetadata::path)).forEach(file -> xml.append("    <file path=\"")
                .append(escapeXml(file.path())).append("\" scope=\"").append(file.scope())
                .append("\" sha256=\"").append(file.sha256()).append("\"/>\n"));
        return xml.append("  </manifest>\n").toString();
    }

    private String buildFindings(List<Finding> findings) {
        Map<String, Long> counts = findings.stream().collect(Collectors.groupingBy(
                Finding::type, LinkedHashMap::new, Collectors.counting()));
        StringBuilder xml = new StringBuilder("  <migration_findings>\n    <summary>\n");
        counts.forEach((type, count) -> xml.append("      <finding_count type=\"").append(type)
                .append("\" count=\"").append(count).append("\" severity=\"")
                .append(severity(type)).append("\"/>\n"));
        xml.append("    </summary>\n");
        findings.stream().sorted(Comparator.comparing(Finding::path).thenComparingInt(Finding::line))
                .forEach(finding -> xml.append("    <finding type=\"").append(finding.type())
                        .append("\" severity=\"").append(severity(finding.type())).append("\" path=\"")
                        .append(escapeXml(finding.path())).append("\" line=\"").append(finding.line())
                        .append("\" token=\"").append(escapeXml(finding.token())).append("\"/>\n"));
        return xml.append("  </migration_findings>\n").toString();
    }

    private String buildParseErrors(List<ParseFailure> errors) {
        StringBuilder xml = new StringBuilder("  <parse_errors count=\"").append(errors.size()).append("\">\n");
        errors.forEach(error -> xml.append("    <parse_error path=\"").append(escapeXml(error.path()))
                .append("\" message=\"").append(escapeXml(error.message())).append("\"/>\n"));
        return xml.append("  </parse_errors>\n").toString();
    }

    private void collectFindings(String path, String content, List<Finding> findings) {
        String[] lines = content.split("\\R", -1);
        for (int index = 0; index < lines.length; index++) {
            for (Map.Entry<String, Pattern> entry : MIGRATION_PATTERNS.entrySet()) {
                Matcher matcher = entry.getValue().matcher(lines[index]);
                if (matcher.find()) {
                    findings.add(new Finding(entry.getKey(), path, index + 1, matcher.group()));
                }
            }
        }
    }

    private void writeCompanionArtifacts(Path output, Path root, Instant generatedAt, List<Section> sections) throws IOException {
        String fileName = output.getFileName().toString();
        int extension = fileName.lastIndexOf('.');
        String stem = extension > 0 ? fileName.substring(0, extension) : fileName;
        Path directory = output.resolveSibling(stem);
        Files.createDirectories(directory);
        for (Section section : sections) {
            String document = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                    + "<context_fragment repository=\"" + escapeXml(root.getFileName().toString())
                    + "\" generated_at=\"" + generatedAt + "\" type=\"" + section.name() + "\">\n"
                    + section.xml() + "</context_fragment>\n";
            Files.writeString(directory.resolve(section.name() + ".xml"), document, StandardCharsets.UTF_8);
        }
    }

    private static Map<String, Pattern> migrationPatterns() {
        Map<String, Pattern> patterns = new LinkedHashMap<>();
        patterns.put("jackson2-api", Pattern.compile("com\\.fasterxml\\.jackson|ObjectMapper|Jackson2ObjectMapperBuilderCustomizer"));
        patterns.put("jackson3-api", Pattern.compile("tools\\.jackson|JsonMapper|JsonMapperBuilderCustomizer"));
        patterns.put("legacy-javax", Pattern.compile("javax\\.(servlet|persistence|validation)"));
        patterns.put("spring-retry", Pattern.compile("org\\.springframework\\.retry|spring-retry|@Retryable|@EnableRetry"));
        patterns.put("removed-test-api", Pattern.compile("@MockBean|@SpyBean|MockitoTestExecutionListener"));
        patterns.put("security-dsl", Pattern.compile("WebSecurityConfigurerAdapter|antMatchers\\(|\\.cors\\(\\)|\\.csrf\\(\\)|\\.and\\(\\)"));
        patterns.put("boot-property", Pattern.compile("spring\\.mvc\\.pathmatch\\.use-suffix-pattern|redirect-uri-template|management\\.server\\.ssl|spring\\.session\\.(redis|mongodb)"));
        patterns.put("deprecated-starter", Pattern.compile("spring-boot-starter-(aop|web|web-services|oauth2-client|oauth2-resource-server|oauth2-authorization-server)"));
        return Map.copyOf(patterns);
    }

    private static String severity(String type) {
        return switch (type) {
            case "legacy-javax", "removed-test-api", "security-dsl" -> "high";
            case "jackson2-api", "spring-retry", "boot-property", "deprecated-starter" -> "medium";
            default -> "info";
        };
    }

    private String determineClassRole(ClassOrInterfaceDeclaration type) {
        if (type.isAnnotationPresent("RestController") || type.isAnnotationPresent("Controller")) return "controller";
        if (type.isAnnotationPresent("Service")) return "service";
        if (type.isAnnotationPresent("Repository")) return "repository";
        if (type.isAnnotationPresent("Entity") || type.isAnnotationPresent("Table")) return "entity";
        if (type.isAnnotationPresent("FeignClient")) return "feign-client";
        if (type.isInterface()) return "interface";
        return "component";
    }

    private void appendAnnotations(StringBuilder xml, List<AnnotationExpr> annotations, String indent) {
        for (AnnotationExpr annotation : annotations) {
            xml.append(indent).append("<annotation name=\"")
                    .append(escapeXml(annotation.getNameAsString())).append("\"/>\n");
        }
    }

    private static String annotationNames(List<AnnotationExpr> annotations) {
        return annotations.stream().map(annotation -> annotation.getNameAsString()).collect(Collectors.joining(", "));
    }

    private static String visibility(com.github.javaparser.ast.nodeTypes.NodeWithModifiers<?> node) {
        if (node.hasModifier(com.github.javaparser.ast.Modifier.Keyword.PUBLIC)) return "public";
        if (node.hasModifier(com.github.javaparser.ast.Modifier.Keyword.PROTECTED)) return "protected";
        if (node.hasModifier(com.github.javaparser.ast.Modifier.Keyword.PRIVATE)) return "private";
        return "package";
    }

    private String redactSensitiveValues(String content) {
        return content.lines().map(this::redactSensitiveLine).collect(Collectors.joining(System.lineSeparator()));
    }

    private String redactSensitiveLine(String line) {
        Matcher assignment = SENSITIVE_ASSIGNMENT.matcher(line);
        if (assignment.matches()) return assignment.group(1) + "[REDACTED]";
        Matcher xml = SENSITIVE_XML_ELEMENT.matcher(line);
        if (xml.matches()) return xml.group(1) + "[REDACTED]" + xml.group(3);
        return line;
    }

    private static String gitValue(Path root, String... arguments) {
        List<String> command = new ArrayList<>(List.of("git", "-C", root.toString()));
        command.addAll(List.of(arguments));
        try {
            Process process = new ProcessBuilder(command).redirectErrorStream(true).start();
            String value = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim();
            return process.waitFor() == 0 ? value : "";
        } catch (IOException exception) {
            return "";
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            return "";
        }
    }

    private static String sha256(String content) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(content.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte value : digest) hex.append(String.format("%02x", value));
            return hex.toString();
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private static boolean isTestSource(String path) {
        String normalized = path.replace('\\', '/');
        return normalized.contains("/src/test/") || normalized.startsWith("src/test/");
    }

    private static String relativePath(Path root, Path file) {
        return root.relativize(file.toAbsolutePath().normalize()).toString().replace('\\', '/');
    }

    private static String cdata(String value) {
        return value.replace("]]>", "]]]]><![CDATA[>");
    }

    private static String escapeXml(String input) {
        if (input == null) return "";
        return input.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\"", "&quot;").replace("'", "&apos;");
    }

    private static String conciseMessage(Exception exception) {
        String message = exception.getMessage();
        if (message == null || message.isBlank()) return exception.getClass().getSimpleName();
        String firstLine = message.lines().findFirst().orElse(message);
        return firstLine.length() > 300 ? firstLine.substring(0, 300) : firstLine;
    }

    private static String wrap(String name, List<String> values) {
        return "  <" + name + ">\n" + String.join("", values) + "  </" + name + ">\n";
    }

    private static int countFileElements(String xml) {
        return (int) Pattern.compile("<(source_file|config_file)\\b").matcher(xml).results().count();
    }

    private static Element child(Element parent, String name) {
        if (parent == null) return null;
        NodeList nodes = parent.getChildNodes();
        for (int index = 0; index < nodes.getLength(); index++) {
            if (nodes.item(index) instanceof Element element && element.getTagName().equals(name)) return element;
        }
        return null;
    }

    private static List<Element> children(Element parent, String name) {
        List<Element> result = new ArrayList<>();
        if (parent == null) return result;
        NodeList nodes = parent.getChildNodes();
        for (int index = 0; index < nodes.getLength(); index++) {
            if (nodes.item(index) instanceof Element element && element.getTagName().equals(name)) result.add(element);
        }
        return result;
    }

    private static String value(Element parent, String name) {
        Element child = child(parent, name);
        return child == null ? "" : child.getTextContent().trim();
    }

    private record Section(String name, String xml) {}
    private record ParseFailure(String path, String message) {}
    private record Finding(String type, String path, int line, String token) {}
    private record FileMetadata(String path, String scope, String sha256) {}
}
