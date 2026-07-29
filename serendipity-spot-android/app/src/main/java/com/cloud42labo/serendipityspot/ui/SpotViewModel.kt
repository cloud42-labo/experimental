package com.cloud42labo.serendipityspot.ui

import android.app.Activity
import android.app.Application
import android.content.Intent
import android.content.IntentSender
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.cloud42labo.serendipityspot.auth.AuthorizationOutcome
import com.cloud42labo.serendipityspot.auth.GoogleAuthManager
import com.cloud42labo.serendipityspot.auth.SignedInUser
import com.cloud42labo.serendipityspot.data.SheetsRepository
import com.cloud42labo.serendipityspot.data.SpotLocalCache
import com.cloud42labo.serendipityspot.notification.NotificationHelper
import com.cloud42labo.serendipityspot.data.Spot
import com.cloud42labo.serendipityspot.location.GeofenceHelper
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SpotUiState(
    val user: SignedInUser? = null,
    val spots: List<Spot> = emptyList(),
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val focusSpotId: String? = null,
    // 通知が来ないときの切り分け用。アプリの動作には影響しない。
    val lastRegistration: String? = null,
    val lastGeofenceEvent: String? = null,
)

class SpotViewModel(application: Application) : AndroidViewModel(application) {

    private val authManager = GoogleAuthManager(application)
    private val repository = SheetsRepository(application)
    private val geofenceHelper = GeofenceHelper(application)

    private var spreadsheetId: String? = null

    private val _uiState = MutableStateFlow(SpotUiState())
    val uiState: StateFlow<SpotUiState> = _uiState.asStateFlow()

    /** Sheets/Driveの許可画面をActivityに出してもらうための依頼。 */
    private val _consentRequests = Channel<IntentSender>(Channel.BUFFERED)
    val consentRequests = _consentRequests.receiveAsFlow()

    init {
        authManager.cachedUser()?.let { user ->
            _uiState.update { it.copy(user = user) }
            refresh()
        }
    }

    fun signIn(activity: Activity) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            runCatching { authManager.signIn(activity) }
                .onSuccess { user ->
                    _uiState.update { it.copy(user = user, isLoading = false) }
                    loadSpots()
                }
                .onFailure { error ->
                    // ユーザーが自分でダイアログを閉じた場合はエラー表示しない
                    val message = if (error is GetCredentialCancellationException) null
                    else error.message ?: "サインインに失敗しました"
                    _uiState.update { it.copy(isLoading = false, errorMessage = message) }
                }
        }
    }

    fun signOut() {
        viewModelScope.launch {
            runCatching { authManager.signOut() }
            spreadsheetId = null
            _uiState.value = SpotUiState()
        }
    }

    fun onAuthorizationResult(data: Intent?) {
        viewModelScope.launch {
            val outcome = runCatching { authManager.authorizationResultFrom(data) }.getOrElse { error ->
                fail(error, "アクセス許可を確認できませんでした")
                return@launch
            }
            when (outcome) {
                is AuthorizationOutcome.Granted -> loadSpots()
                is AuthorizationOutcome.ConsentRequired -> _uiState.update {
                    it.copy(
                        isLoading = false,
                        errorMessage = "スプレッドシートへのアクセスを許可すると利用できます",
                    )
                }
            }
        }
    }

    /** 診断表示を最新にする。SharedPreferences から読み直すだけ。 */
    fun refreshDiagnostics() {
        val app = getApplication<Application>()
        _uiState.update {
            it.copy(
                lastRegistration = SpotLocalCache.loadLastRegistration(app),
                lastGeofenceEvent = SpotLocalCache.loadLastGeofenceEvent(app),
            )
        }
    }

    /**
     * 通知を出す経路が生きているかだけを確かめる。
     * ジオフェンスを経由せず、受信側と同じ NotificationHelper を直接呼ぶ。
     */
    fun sendTestNotification() {
        val app = getApplication<Application>()
        val spot = _uiState.value.spots.firstOrNull()
            ?: Spot(id = "test", lat = 0.0, lng = 0.0, title = "テスト", memo = "通知の確認用")
        NotificationHelper.ensureChannel(app)
        NotificationHelper.notifyNearby(app, spot)
    }

    fun consumeFocusRequest() {
        _uiState.update { it.copy(focusSpotId = null) }
    }

    fun focusSpot(spotId: String) {
        _uiState.update { it.copy(focusSpotId = spotId) }
    }

    fun refresh() {
        if (_uiState.value.user == null) return
        viewModelScope.launch { loadSpots() }
    }

    fun addSpot(lat: Double, lng: Double, title: String, memo: String) {
        if (_uiState.value.user == null || title.isBlank()) return
        val id = spreadsheetId ?: return
        viewModelScope.launch {
            val token = requireAccessToken() ?: return@launch

            runCatching {
                val sheets = authManager.sheetsService(token)
                repository.appendSpot(sheets, id, lat, lng, title, memo)
            }.onSuccess {
                // 追加直後の Spot は行番号を持たない（編集・削除ができない）。
                // シートから読み直して確定させる。ジオフェンスとキャッシュもここで揃う。
                loadSpots()
            }.onFailure { error -> fail(error, "保存に失敗しました") }
        }
    }

    fun editSpot(spot: Spot, title: String, memo: String) {
        if (_uiState.value.user == null || title.isBlank()) return
        val id = spreadsheetId ?: return
        viewModelScope.launch {
            val token = requireAccessToken() ?: return@launch
            runCatching {
                val sheets = authManager.sheetsService(token)
                repository.updateSpotText(sheets, id, spot, title, memo)
            }.onSuccess { updated ->
                if (updated) loadSpots() else failStale()
            }.onFailure { error -> fail(error, "更新に失敗しました") }
        }
    }

    fun deleteSpot(spot: Spot) {
        if (_uiState.value.user == null) return
        val id = spreadsheetId ?: return
        viewModelScope.launch {
            val token = requireAccessToken() ?: return@launch
            runCatching {
                val sheets = authManager.sheetsService(token)
                repository.deleteSpot(sheets, id, spot)
            }.onSuccess { deleted ->
                if (deleted) loadSpots() else failStale()
            }.onFailure { error -> fail(error, "削除に失敗しました") }
        }
    }

    /** シート上の行が特定できないとき。読み直せば直る。 */
    private fun failStale() {
        _uiState.update {
            it.copy(isLoading = false, errorMessage = "対象の行を特定できませんでした。読み込み直してください")
        }
    }

    private suspend fun loadSpots() {
        val token = requireAccessToken() ?: return
        runCatching {
            val sheets = authManager.sheetsService(token)
            val drive = authManager.driveService(token)
            val id = spreadsheetId
                ?: repository.ensureSpreadsheet(sheets, drive).also { spreadsheetId = it }
            val spots = repository.loadSpots(sheets, id)
            geofenceHelper.resync(spots)
            spots
        }.onSuccess { spots ->
            _uiState.update { it.copy(spots = spots, isLoading = false) }
            refreshDiagnostics()
        }.onFailure { error -> fail(error, "読み込みに失敗しました") }
    }

    /**
     * アクセストークンを取る。まだ許可されていなければ許可画面をActivityに依頼し、
     * nullを返す（結果は[onAuthorizationResult]に戻ってくる）。
     */
    private suspend fun requireAccessToken(): String? {
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }

        val outcome = runCatching { authManager.authorize() }.getOrElse { error ->
            fail(error, "アクセス許可の取得に失敗しました")
            return null
        }

        return when (outcome) {
            is AuthorizationOutcome.Granted -> outcome.accessToken
            is AuthorizationOutcome.ConsentRequired -> {
                _consentRequests.send(outcome.intentSender)
                _uiState.update { it.copy(isLoading = false) }
                null
            }
        }
    }

    private fun fail(error: Throwable, fallback: String) {
        _uiState.update { it.copy(isLoading = false, errorMessage = error.message ?: fallback) }
    }
}
