import java.util.Properties

plugins {
    id("com.android.application")
}

val tmapLocal = Properties().apply {
    rootProject.file(".env").takeIf { it.isFile }?.readText(Charsets.UTF_8)
        ?.removePrefix("\uFEFF")?.reader()?.use { load(it) }
}
fun tmapSetting(name: String): String = (System.getenv(name) ?: tmapLocal.getProperty(name, ""))
    .trim().trim('"', '\'')
fun configString(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "com.example.pleosprojectv01"
    compileSdk {
        version = release(36) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.example.pleosprojectv01.convoy"
        minSdk = 28
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "TMAP_NATIVE_APP_KEY", configString(tmapSetting("TMAP_APP_KEY")))
        buildConfigField("String", "TMAP_CLIENT_ID", configString(tmapSetting("TMAP_CLIENT_ID")))
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        buildConfig = true
        dataBinding = true
    }
}

dependencies {
    implementation("com.tmapmobility.tmap:tmap-ui-sdk:1.0.0.0160")
    implementation("com.tmapmobility.tmap:navigation-sdk:11.0.0.1117")
    implementation("com.tmapmobility.tmap:TmapEngineCommonData:11.0.0.1117")
    implementation("androidx.appcompat:appcompat:1.5.1")
    implementation("com.google.android.material:material:1.6.1")
    implementation("ai.pleos.playground:FusedLocation:1.1.3")
    implementation("ai.pleos.playground:NaviHelper:3.0.5")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
}
