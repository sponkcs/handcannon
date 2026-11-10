plugins { java }
group = "dev.handcannon"
version = "0.8.0"
repositories {
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
}
dependencies { compileOnly("io.papermc.paper:paper-api:26.2.build.+") }
java { toolchain.languageVersion.set(JavaLanguageVersion.of(25)) }
tasks.processResources { filesMatching("plugin.yml") { expand("version" to project.version) } }
