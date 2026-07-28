package com.cloud42labo.serendipityspot.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.cloud42labo.serendipityspot.auth.GoogleAuthManager
import com.cloud42labo.serendipityspot.data.Spot
import com.cloud42labo.serendipityspot.data.SheetsRepository
import com.cloud42labo.serendipityspot.location.GeofenceHelper
import com.google.android.gms.auth.api.signin.GoogleSignInAccount
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class SpotUiState(
    val account: GoogleSignInAccount? = null,
    val spots: List<Spot> = emptyList(),
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val focusSpotId: String? = null,
)

class SpotViewModel(application: Application) : AndroidViewModel(application) {

    private val authManager = GoogleAuthManager(application)
    private val repository = SheetsRepository(application)
    private val geofenceHelper = GeofenceHelper(application)

    private var spreadsheetId: String? = null

    private val _uiState = MutableStateFlow(SpotUiState())
    val uiState: StateFlow<SpotUiState> = _uiState.asStateFlow()

    val signInIntent get() = authManager.signInIntent()

    init {
        authManager.lastSignedInAccount()?.let { account ->
            _uiState.value = _uiState.value.copy(account = account)
            refresh()
        }
    }

    fun onSignInResult(account: GoogleSignInAccount?) {
        if (account == null) {
            _uiState.value = _uiState.value.copy(errorMessage = "サインインに失敗しました")
            return
        }
        _uiState.value = _uiState.value.copy(account = account, errorMessage = null)
        refresh()
    }

    fun signOut() {
        authManager.signOut()
        _uiState.value = SpotUiState()
    }

    fun consumeFocusRequest() {
        _uiState.value = _uiState.value.copy(focusSpotId = null)
    }

    fun focusSpot(spotId: String) {
        _uiState.value = _uiState.value.copy(focusSpotId = spotId)
    }

    fun refresh() {
        val account = _uiState.value.account ?: return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            runCatching {
                val sheets = authManager.sheetsService(account)
                val drive = authManager.driveService(account)
                val id = spreadsheetId ?: repository.ensureSpreadsheet(sheets, drive).also { spreadsheetId = it }
                val spots = repository.loadSpots(sheets, id)
                geofenceHelper.resync(spots)
                spots
            }.onSuccess { spots ->
                _uiState.value = _uiState.value.copy(spots = spots, isLoading = false)
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    errorMessage = error.message ?: "読み込みに失敗しました",
                )
            }
        }
    }

    fun addSpot(lat: Double, lng: Double, title: String, memo: String) {
        val account = _uiState.value.account ?: return
        val id = spreadsheetId ?: return
        if (title.isBlank()) return

        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
            runCatching {
                val sheets = authManager.sheetsService(account)
                val spot = repository.appendSpot(sheets, id, lat, lng, title, memo)
                val newSpots = _uiState.value.spots + spot
                geofenceHelper.resync(newSpots)
                newSpots
            }.onSuccess { spots ->
                _uiState.value = _uiState.value.copy(spots = spots, isLoading = false)
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    errorMessage = error.message ?: "保存に失敗しました",
                )
            }
        }
    }
}
