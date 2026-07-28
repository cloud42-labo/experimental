import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val localProperties = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.cloud42labo.serendipityspot"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.cloud42labo.serendipityspot"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"

        manifestPlaceholders["mapsApiKey"] =
            (localProperties.getProperty("MAPS_API_KEY") ?: "").ifBlank { "MISSING_MAPS_API_KEY" }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
            excludes += "META-INF/DEPENDENCIES"
        }
    }
}

dependencies {
    // Compose
    val composeBom = platform("androidx.compose:compose-bom:2024.09.03")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // Maps
    implementation("com.google.android.gms:play-services-maps:19.0.0")
    implementation("com.google.maps.android:maps-compose:6.2.1")

    // Location / Geofencing
    implementation("com.google.android.gms:play-services-location:21.3.0")

    // Google Sign-In
    implementation("com.google.android.gms:play-services-auth:21.2.0")

    // Google Sheets / Drive API (Sheetsを個人スプレッドシートとしてDBに使う)
    implementation("com.google.api-client:google-api-client-android:2.7.0") {
        exclude(group = "org.apache.httpcomponents")
    }
    implementation("com.google.apis:google-api-services-sheets:v4-rev20240814-2.0.0")
    implementation("com.google.apis:google-api-services-drive:v3-rev20240914-2.0.0")
    implementation("com.google.http-client:google-http-client-gson:1.45.0") {
        exclude(group = "org.apache.httpcomponents")
    }

    // Coroutines + Play Services Task interop
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.9.0")

    implementation("androidx.core:core-ktx:1.13.1")

    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
