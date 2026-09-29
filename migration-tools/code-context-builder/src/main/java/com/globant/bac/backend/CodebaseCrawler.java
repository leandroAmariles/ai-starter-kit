package com.globant.bac.backend;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ParserConfiguration;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Set;

/**
 * High-performance repository crawler and AST context generator for Java microservices.
 * Produces an AI-optimized XML schema containing metadata, REST contracts, models, and configurations.
 */
public class CodebaseCrawler {

    static {
        StaticJavaParser.setConfiguration(new ParserConfiguration()
                .setLanguageLevel(ParserConfiguration.LanguageLevel.BLEEDING_EDGE));
    }

    private static final Set<String> IGNORED_DIRECTORIES = Set.of(
            ".git", ".svn", ".hg",
            "target", "build", ".gradle", "bin", "out",
            ".idea", ".vscode", ".settings",
            "node_modules",
            "migration-tools", ".ai"
    );

    private static final Set<String> TARGET_CONFIG_FILES = Set.of(
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "application.yml",
            "application.yaml",
            "application.properties",
            "bootstrap.yml",
            "bootstrap.yaml"
    );

    public record CrawlResult(
            List<Path> javaSourceFiles,
            List<Path> configFiles
    ) {}

    public record ContextResult(
            Path outputFile,
            int includedFiles,
            int truncatedFiles,
            int omittedFiles,
            List<Path> unreadableFiles
    ) {}

    public CrawlResult crawl(Path rootPath) throws IOException {
        List<Path> javaFiles = new ArrayList<>();
        List<Path> configFiles = new ArrayList<>();

        Files.walkFileTree(rootPath.toAbsolutePath().normalize(), new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attrs) {
                if (IGNORED_DIRECTORIES.contains(dir.getFileName().toString())) {
                    return FileVisitResult.SKIP_SUBTREE;
                }
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) {
                String fileName = file.getFileName().toString();

                if (fileName.endsWith(".java")) {
                    javaFiles.add(file);
                } else if (TARGET_CONFIG_FILES.contains(fileName.toLowerCase())) {
                    configFiles.add(file);
                }

                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult visitFileFailed(Path file, IOException exc) {
                return FileVisitResult.CONTINUE;
            }
        });

        Comparator<Path> byPath = Comparator.comparing(Path::toString);
        javaFiles.sort(byPath);
        configFiles.sort(byPath);
        return new CrawlResult(List.copyOf(javaFiles), List.copyOf(configFiles));
    }

    /**
     * Generates an AI-optimized XML context artifact containing codebase architecture, REST APIs, and models.
     */
    public ContextResult writeContext(Path rootPath, CrawlResult crawlResult, Path outputPath) throws IOException {
        return new MigrationContextWriter().write(rootPath, crawlResult, outputPath);
    }

    public static void main(String[] args) {
        Path rootPath = Paths.get(args.length > 0 ? args[0] : ".");
        Path outputPath = Paths.get(args.length > 1 ? args[1] : ".ai/migration-context/context.xml");
        CodebaseCrawler crawler = new CodebaseCrawler();

        try {
            System.out.println("Scanning microservice project root: " + rootPath.toAbsolutePath());
            CrawlResult result = crawler.crawl(rootPath);

            System.out.println("\n=== Crawl Summary ===");
            System.out.printf("Java Files Discovered:   %d%n", result.javaSourceFiles().size());
            System.out.printf("Config Files Discovered: %d%n", result.configFiles().size());

            ContextResult contextResult = crawler.writeContext(rootPath, result, outputPath);
            System.out.println("\n=== XML Context Output ===");
            System.out.println("Output File: " + contextResult.outputFile());
            System.out.printf("Included Files: %d%n", contextResult.includedFiles());
            System.out.printf("Truncated Files: %d%n", contextResult.truncatedFiles());
            System.out.printf("Omitted Files: %d%n", contextResult.omittedFiles());
            System.out.printf("Unreadable Files: %d%n", contextResult.unreadableFiles().size());

        } catch (IOException e) {
            System.err.println("Failed to build codebase context XML: " + e.getMessage());
            System.exit(1);
        }
    }
}