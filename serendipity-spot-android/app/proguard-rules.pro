# Google API Client uses reflection-based JSON parsing.
-keep class com.google.api.services.sheets.v4.model.** { *; }
-keep class com.google.api.services.drive.v3.model.** { *; }
-keep class com.google.api.client.** { *; }
-dontwarn com.google.api.client.**
