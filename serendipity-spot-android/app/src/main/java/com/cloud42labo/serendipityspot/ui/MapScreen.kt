package com.cloud42labo.serendipityspot.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.google.android.gms.maps.model.CameraPosition
import com.google.android.gms.maps.model.LatLng
import com.google.maps.android.compose.GoogleMap
import com.google.maps.android.compose.MapProperties
import com.google.maps.android.compose.MapUiSettings
import com.google.maps.android.compose.Marker
import com.google.maps.android.compose.MarkerState
import com.google.maps.android.compose.rememberCameraPositionState

private val DEFAULT_CENTER = LatLng(35.6581, 139.7017)

@Composable
fun MapScreen(
    uiState: SpotUiState,
    hasLocationPermission: Boolean,
    onSignInClick: () -> Unit,
    onSaveSpot: (lat: Double, lng: Double, title: String, memo: String) -> Unit,
    onFocusConsumed: () -> Unit,
) {
    val cameraPositionState = rememberCameraPositionState {
        position = CameraPosition.fromLatLngZoom(DEFAULT_CENTER, 15f)
    }
    val snackbarHostState = remember { SnackbarHostState() }

    var pendingLatLng by remember { mutableStateOf<LatLng?>(null) }

    LaunchedEffect(uiState.focusSpotId) {
        val target = uiState.spots.firstOrNull { it.id == uiState.focusSpotId } ?: return@LaunchedEffect
        cameraPositionState.position = CameraPosition.fromLatLngZoom(LatLng(target.lat, target.lng), 17f)
        onFocusConsumed()
    }

    LaunchedEffect(uiState.errorMessage) {
        uiState.errorMessage?.let { snackbarHostState.showSnackbar(it) }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            GoogleMap(
                modifier = Modifier.fillMaxSize(),
                cameraPositionState = cameraPositionState,
                properties = MapProperties(isMyLocationEnabled = hasLocationPermission && uiState.account != null),
                uiSettings = MapUiSettings(zoomControlsEnabled = false, myLocationButtonEnabled = false),
                onMapClick = { latLng ->
                    if (uiState.account != null) pendingLatLng = latLng
                },
            ) {
                uiState.spots.forEach { spot ->
                    Marker(
                        state = MarkerState(LatLng(spot.lat, spot.lng)),
                        title = spot.title,
                        snippet = spot.memo,
                    )
                }
            }

            if (uiState.account == null) {
                SignInOverlay(onSignInClick = onSignInClick)
            } else {
                Text(
                    text = "地図をタップしてスポットを登録",
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 16.dp)
                        .background(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.large)
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    style = MaterialTheme.typography.labelLarge,
                )
            }

            if (uiState.isLoading) {
                CircularProgressIndicator(
                    modifier = Modifier.align(Alignment.Center),
                )
            }
        }
    }

    pendingLatLng?.let { latLng ->
        RegisterSheet(
            onDismiss = { pendingLatLng = null },
            onSave = { title, memo ->
                onSaveSpot(latLng.latitude, latLng.longitude, title, memo)
                pendingLatLng = null
            },
        )
    }
}

@Composable
private fun SignInOverlay(onSignInClick: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Card(
            elevation = CardDefaults.cardElevation(defaultElevation = 8.dp),
            modifier = Modifier.padding(32.dp),
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(
                    imageVector = Icons.Filled.LocationOn,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(40.dp),
                )
                Spacer(modifier = Modifier.height(12.dp))
                Text("Serendipity Spot", style = MaterialTheme.typography.titleLarge)
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    "Googleアカウントでログインすると、スポットがあなたのスプレッドシートに保存されます",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.height(20.dp))
                Button(onClick = onSignInClick, modifier = Modifier.fillMaxWidth()) {
                    Text("Googleでログイン")
                }
            }
        }
    }
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun RegisterSheet(
    onDismiss: () -> Unit,
    onSave: (title: String, memo: String) -> Unit,
) {
    val sheetState = rememberModalBottomSheetState()
    var title by remember { mutableStateOf("") }
    var memo by remember { mutableStateOf("") }

    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        Column(modifier = Modifier.fillMaxWidth().padding(24.dp)) {
            Text("スポット保存", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(16.dp))
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                label = { Text("名前") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedTextField(
                value = memo,
                onValueChange = { memo = it },
                label = { Text("ひとことメモ") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
            )
            Spacer(modifier = Modifier.height(20.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onDismiss) { Text("キャンセル") }
                Spacer(modifier = Modifier.width(8.dp))
                ElevatedButton(
                    onClick = { onSave(title, memo) },
                    enabled = title.isNotBlank(),
                ) { Text("保存") }
            }
            Spacer(modifier = Modifier.height(8.dp))
        }
    }
}
