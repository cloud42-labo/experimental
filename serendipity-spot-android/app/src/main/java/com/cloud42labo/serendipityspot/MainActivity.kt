package com.cloud42labo.serendipityspot

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.cloud42labo.serendipityspot.ui.MapScreen
import com.cloud42labo.serendipityspot.ui.SpotViewModel
import com.cloud42labo.serendipityspot.ui.theme.SerendipitySpotTheme

class MainActivity : ComponentActivity() {

    private val viewModel: SpotViewModel by viewModels()

    /** Sheets/Driveスコープの同意画面。ViewModelからの依頼で起動する。 */
    private val consentLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult()
    ) { result ->
        viewModel.onAuthorizationResult(result.data)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        handleFocusIntent(intent)

        setContent {
            SerendipitySpotTheme {
                Surface {
                    val uiState by viewModel.uiState.collectAsState()
                    var hasForegroundLocation by remember { mutableStateOf(hasForegroundLocationPermission()) }
                    var hasBackgroundLocation by remember { mutableStateOf(hasBackgroundLocationPermission()) }

                    val backgroundLocationLauncher = rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestPermission()
                    ) { granted -> hasBackgroundLocation = granted }

                    val foregroundLauncher = rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestMultiplePermissions()
                    ) { grants ->
                        hasForegroundLocation = grants[Manifest.permission.ACCESS_FINE_LOCATION] == true ||
                            grants[Manifest.permission.ACCESS_COARSE_LOCATION] == true
                        if (hasForegroundLocation && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            backgroundLocationLauncher.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                        }
                    }

                    LaunchedEffect(Unit) {
                        viewModel.consentRequests.collect { intentSender ->
                            consentLauncher.launch(IntentSenderRequest.Builder(intentSender).build())
                        }
                    }

                    LaunchedEffect(Unit) {
                        val permissions = mutableListOf(
                            Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION,
                        )
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            permissions += Manifest.permission.POST_NOTIFICATIONS
                        }
                        if (!hasForegroundLocation) {
                            foregroundLauncher.launch(permissions.toTypedArray())
                        } else if (!hasBackgroundLocation && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            backgroundLocationLauncher.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                        }
                    }

                    Box {
                        MapScreen(
                            uiState = uiState,
                            hasLocationPermission = hasForegroundLocation,
                            onSignInClick = { viewModel.signIn(this@MainActivity) },
                            onSignOutClick = viewModel::signOut,
                            onSaveSpot = viewModel::addSpot,
                            onEditSpot = viewModel::editSpot,
                            onDeleteSpot = viewModel::deleteSpot,
                            onTestNotification = viewModel::sendTestNotification,
                            onRefreshDiagnostics = viewModel::refreshDiagnostics,
                            onFocusConsumed = viewModel::consumeFocusRequest,
                        )

                        if (uiState.user != null && hasForegroundLocation && !hasBackgroundLocation) {
                            BackgroundLocationHint()
                        }
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleFocusIntent(intent)
    }

    private fun handleFocusIntent(intent: Intent?) {
        val spotId = intent?.getStringExtra(EXTRA_FOCUS_SPOT_ID) ?: return
        viewModel.focusSpot(spotId)
    }

    private fun hasForegroundLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun hasBackgroundLocationPermission(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return true
        return ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_BACKGROUND_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
    }

    companion object {
        const val EXTRA_FOCUS_SPOT_ID = "extra_focus_spot_id"
    }
}

@Composable
private fun BackgroundLocationHint() {
    val context = LocalContext.current
    Box(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    "アプリを閉じていても通知するには、位置情報の権限を「常に許可」に" +
                        "変更してください。",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(modifier = Modifier.padding(top = 8.dp))
                Box(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        horizontalArrangement = Arrangement.End,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Button(onClick = {
                            val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                                data = Uri.fromParts("package", context.packageName, null)
                            }
                            context.startActivity(intent)
                        }) {
                            Text("設定を開く")
                        }
                    }
                }
            }
        }
    }
}
