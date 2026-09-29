package com.globant.bac.backend;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

import javax.xml.parsers.DocumentBuilderFactory;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * Tests for migration context generation.
 */
class AppTest {

    @TempDir
    Path temporaryDirectory;

    @Test
    void writesMigrationAwareContextAndCompanionArtifacts() throws IOException {
        Path sourceDirectory = Files.createDirectories(temporaryDirectory.resolve("src/main/java/example"));
        Path testDirectory = Files.createDirectories(temporaryDirectory.resolve("src/test/java/example"));
        Path resourcesDirectory = Files.createDirectories(temporaryDirectory.resolve("src/main/resources"));
        Files.writeString(sourceDirectory.resolve("Application.java"), """
                package example;
                import com.fasterxml.jackson.databind.ObjectMapper;
                class Application extends Base implements Runnable {
                    private String value = "hidden";
                    Application(String value) {}
                    public void run() { new ObjectMapper().findAndRegisterModules(); }
                }
                """);
        Files.writeString(testDirectory.resolve("ApplicationTest.java"), """
                package example;
                import org.springframework.boot.test.mock.mockito.MockBean;
                class ApplicationTest { @MockBean Object service; }
                """);
        Files.writeString(resourcesDirectory.resolve("application.properties"), "service.password=secret-value\nservice.name=context-builder");
        Files.writeString(temporaryDirectory.resolve("pom.xml"), """
                <project>
                  <modelVersion>4.0.0</modelVersion>
                  <parent><groupId>com.bac.core</groupId><artifactId>parent</artifactId><version>1</version></parent>
                  <groupId>example</groupId><artifactId>sample</artifactId><version>1</version>
                  <dependencies><dependency><groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-web</artifactId></dependency></dependencies>
                </project>
                """);

        CodebaseCrawler crawler = new CodebaseCrawler();
        CodebaseCrawler.CrawlResult crawlResult = crawler.crawl(temporaryDirectory);
        Path output = temporaryDirectory.resolve("generated/sample.xml");
        CodebaseCrawler.ContextResult contextResult = crawler.writeContext(temporaryDirectory, crawlResult, output);

        String context = Files.readString(output);
        assertEquals(2, crawlResult.javaSourceFiles().size());
        assertEquals(2, crawlResult.configFiles().size());
        assertEquals(4, contextResult.includedFiles());
        assertTrue(context.contains("src/main/java/example/Application.java"));
        assertTrue(context.contains("src/test/java/example/ApplicationTest.java"));
        assertTrue(context.contains("src/main/resources/application.properties"));
        assertTrue(context.contains("[REDACTED]"));
        assertTrue(context.contains("service.name=context-builder"));
        assertTrue(context.contains("<maven_model>"));
        assertTrue(context.contains("artifact_id=\"spring-boot-starter-web\""));
        assertTrue(context.contains("type=\"jackson2-api\""));
        assertTrue(context.contains("type=\"removed-test-api\""));
        assertTrue(context.contains("sha256="));
        assertTrue(context.contains("<constructor name=\"Application\""));
        assertTrue(context.contains("implements=\"[Runnable]\""));
        assertTrue(context.contains("findAndRegisterModules@"));
        assertTrue(Files.isRegularFile(output.resolveSibling("sample/manifest.xml")));
        assertTrue(Files.isRegularFile(output.resolveSibling("sample/maven_model.xml")));
        assertTrue(Files.isRegularFile(output.resolveSibling("sample/tests.xml")));
        assertWellFormedXml(output);
        try (var companionFiles = Files.list(output.resolveSibling("sample"))) {
            for (Path companion : companionFiles.filter(path -> path.toString().endsWith(".xml")).toList()) {
                assertWellFormedXml(companion);
            }
        }
    }

    @Test
    void reportsJavaParserFailuresWithPathsAndMessages() throws IOException {
        Path sourceDirectory = Files.createDirectories(temporaryDirectory.resolve("broken/src/main/java/example"));
        Files.writeString(sourceDirectory.resolve("Broken.java"), "class Broken { void missing( }");

        CodebaseCrawler crawler = new CodebaseCrawler();
        CodebaseCrawler.CrawlResult crawlResult = crawler.crawl(temporaryDirectory.resolve("broken"));
        Path output = temporaryDirectory.resolve("generated/broken.xml");
        CodebaseCrawler.ContextResult result = crawler.writeContext(
                temporaryDirectory.resolve("broken"), crawlResult, output);

        String context = Files.readString(output);
        assertEquals(1, result.unreadableFiles().size());
        assertTrue(context.contains("<parse_errors count=\"1\">"));
        assertTrue(context.contains("path=\"src/main/java/example/Broken.java\""));
        assertWellFormedXml(output);
    }

    private void assertWellFormedXml(Path xmlFile) throws IOException {
        try {
            DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(xmlFile.toFile());
        } catch (Exception exception) {
            throw new IOException("Generated XML is not well formed: " + xmlFile, exception);
        }
    }
}
