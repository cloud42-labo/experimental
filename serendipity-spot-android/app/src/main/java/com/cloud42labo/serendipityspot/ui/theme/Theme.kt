package com.cloud42labo.serendipityspot.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val LightColors = lightColorScheme(
    primary = Indigo600,
    onPrimary = androidx.compose.ui.graphics.Color.White,
    primaryContainer = Indigo50,
    background = AppBackground,
    surface = androidx.compose.ui.graphics.Color.White,
    onSurface = Slate900,
    onSurfaceVariant = Slate500,
)

@Composable
fun SerendipitySpotTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LightColors,
        content = content,
    )
}
