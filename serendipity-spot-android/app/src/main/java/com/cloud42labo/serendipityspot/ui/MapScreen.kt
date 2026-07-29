package com.cloud42labo.serendipityspot.ui

import android.annotation.SuppressLint
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.BottomSheetScaffold
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedButton
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberBottomSheetScaffoldState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.cloud42labo.serendipityspot.data.Spot
import com.google.android.gms.location.LocationServices
import com.google.android.gms.maps.model.CameraPosition
import com.google.android.gms.maps.model.LatLng
import com.google.maps.android.compose.GoogleMap
import com.google.maps.android.compose.MapProperties
import com.google.maps.android.compose.MapUiSettings
import com.google.maps.android.compose.Marker
import com.google.maps.android.compose.MarkerState
import com.google.maps.android.compose.rememberCameraPositionState
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await

/** 現在地が取れるまでの暫定表示（渋谷）。取れ次第そちらへ移す。 */
private val FALLBACK_CENTER = LatLng(35.6581, 139.7017)
private const val SPOT_ZOOM = 17f
private const val CURRENT_LOCATION_ZOOM = 16f

@OptIn(ExperimentalMaterial3Api::class)
@SuppressLint("MissingPermission")
@Composable
fun MapScreen(
    uiState: SpotUiState,
    hasLocationPermission: Boolean,
    onSignInClick: () -> Unit,
    onSignOutClick: () -> Unit,
    onSaveSpot: (lat: Double, lng: Double, title: String, memo: String) -> Unit,
    onEditSpot: (spot: Spot, title: String, memo: String) -> Unit,
    onDeleteSpot: (spot: Spot) -> Unit,
    onFocusConsumed: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val scaffoldState = rememberBottomSheetScaffoldState()
    val snackbarHostState = remember { SnackbarHostState() }

    val cameraPositionState = rememberCameraPositionState {
        position = CameraPosition.fromLatLngZoom(FALLBACK_CENTER, CURRENT_LOCATION_ZOOM)
    }

    var pendingLatLng by remember { mutableStateOf<LatLng?>(null) }
    var editingSpot by remember { mutableStateOf<Spot?>(null) }
    var deletingSpot by remember { mutableStateOf<Spot?>(null) }
    // 初回だけ現在地へ寄せる。以後はユーザーの操作を邪魔しない。
    var initialLocationApplied by rememberSaveable { mutableStateOf(false) }

    LaunchedEffect(hasLocationPermission) {
        if (!hasLocationPermission || initialLocationApplied) return@LaunchedEffect
        val client = LocationServices.getFusedLocationProviderClient(context)
        val location = runCatching { client.lastLocation.await() }.getOrNull()
        if (location != null) {
            cameraPositionState.position = CameraPosition.fromLatLngZoom(
                LatLng(location.latitude, location.longitude),
                CURRENT_LOCATION_ZOOM,
            )
        }
        initialLocationApplied = true
    }

    LaunchedEffect(uiState.focusSpotId) {
        val target = uiState.spots.firstOrNull { it.id == uiState.focusSpotId } ?: return@LaunchedEffect
        cameraPositionState.position =
            CameraPosition.fromLatLngZoom(LatLng(target.lat, target.lng), SPOT_ZOOM)
        onFocusConsumed()
    }

    LaunchedEffect(uiState.errorMessage) {
        uiState.errorMessage?.let { snackbarHostState.showSnackbar(it) }
    }

    val signedIn = uiState.user != null

    BottomSheetScaffold(
        scaffoldState = scaffoldState,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        sheetPeekHeight = if (signedIn) 112.dp else 0.dp,
        topBar = {
            TopAppBar(
                title = { Text("Serendipity Spot") },
                actions = {
                    if (signedIn) {
                        TextButton(onClick = onSignOutClick) { Text("ログアウト") }
                    }
                },
            )
        },
        sheetContent = {
            SpotListSheet(
                spots = uiState.spots,
                onEditClick = { editingSpot = it },
                onDeleteClick = { deletingSpot = it },
                onSpotClick = { spot ->
                    cameraPositionState.position =
                        CameraPosition.fromLatLngZoom(LatLng(spot.lat, spot.lng), SPOT_ZOOM)
                    scope.launch { scaffoldState.bottomSheetState.partialExpand() }
                },
            )
        },
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            GoogleMap(
                modifier = Modifier.fillMaxSize(),
                cameraPositionState = cameraPositionState,
                properties = MapProperties(isMyLocationEnabled = hasLocationPermission && signedIn),
                // 標準の現在地ボタンは地図の右上に固定され動かせないため使わない。
                // 代わりに同じ働きの FAB を右下（親指の届く位置）に置く。
                uiSettings = MapUiSettings(
                    zoomControlsEnabled = false,
                    myLocationButtonEnabled = false,
                ),
                onMapClick = { latLng ->
                    if (signedIn) pendingLatLng = latLng
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

            if (!signedIn) {
                SignInOverlay(onSignInClick = onSignInClick)
            }

            if (signedIn && hasLocationPermission) {
                FloatingActionButton(
                    onClick = {
                        scope.launch {
                            val client = LocationServices.getFusedLocationProviderClient(context)
                            val location = runCatching { client.lastLocation.await() }.getOrNull()
                            if (location != null) {
                                cameraPositionState.position = CameraPosition.fromLatLngZoom(
                                    LatLng(location.latitude, location.longitude),
                                    CURRENT_LOCATION_ZOOM,
                                )
                            } else {
                                snackbarHostState.showSnackbar("現在地を取得できませんでした")
                            }
                        }
                    },
                    modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp),
                ) {
                    Icon(
                        imageVector = Icons.Filled.LocationOn,
                        contentDescription = "現在地へ移動",
                    )
                }
            }

            if (uiState.isLoading) {
                CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
            }
        }
    }

    editingSpot?.let { spot ->
        EditSpotDialog(
            spot = spot,
            onDismiss = { editingSpot = null },
            onSave = { title, memo ->
                onEditSpot(spot, title, memo)
                editingSpot = null
            },
        )
    }

    deletingSpot?.let { spot ->
        AlertDialog(
            onDismissRequest = { deletingSpot = null },
            title = { Text("スポットを削除") },
            text = { Text("「${spot.title}」を削除します。スプレッドシートからも消えます。") },
            confirmButton = {
                TextButton(onClick = {
                    onDeleteSpot(spot)
                    deletingSpot = null
                }) { Text("削除") }
            },
            dismissButton = {
                TextButton(onClick = { deletingSpot = null }) { Text("キャンセル") }
            },
        )
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
private fun SpotListSheet(
    spots: List<Spot>,
    onSpotClick: (Spot) -> Unit,
    onEditClick: (Spot) -> Unit,
    onDeleteClick: (Spot) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 400.dp)
            .padding(bottom = 16.dp),
    ) {
        Text(
            text = "登録スポット（${spots.size}）",
            style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.padding(horizontal = 24.dp),
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = "地図をタップすると新しいスポットを登録できます",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp),
        )
        Spacer(modifier = Modifier.height(12.dp))
        HorizontalDivider()

        if (spots.isEmpty()) {
            Text(
                text = "まだ登録がありません。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(24.dp),
            )
        } else {
            LazyColumn {
                items(spots, key = { it.id }) { spot ->
                    ListItem(
                        headlineContent = { Text(spot.title) },
                        supportingContent = {
                            if (spot.memo.isNotBlank()) Text(spot.memo)
                        },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Filled.LocationOn,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        },
                        trailingContent = {
                            Row {
                                IconButton(onClick = { onEditClick(spot) }) {
                                    Icon(
                                        imageVector = Icons.Filled.Edit,
                                        contentDescription = "${spot.title} を編集",
                                    )
                                }
                                IconButton(onClick = { onDeleteClick(spot) }) {
                                    Icon(
                                        imageVector = Icons.Filled.Delete,
                                        contentDescription = "${spot.title} を削除",
                                        tint = MaterialTheme.colorScheme.error,
                                    )
                                }
                            }
                        },
                        modifier = Modifier.clickable { onSpotClick(spot) },
                    )
                }
            }
        }
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

@OptIn(ExperimentalMaterial3Api::class)
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

@Composable
private fun EditSpotDialog(
    spot: Spot,
    onDismiss: () -> Unit,
    onSave: (title: String, memo: String) -> Unit,
) {
    var title by remember(spot.id) { mutableStateOf(spot.title) }
    var memo by remember(spot.id) { mutableStateOf(spot.memo) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("スポットを編集") },
        text = {
            Column {
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
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onSave(title, memo) },
                enabled = title.isNotBlank(),
            ) { Text("保存") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("キャンセル") }
        },
    )
}
