package com.cloud42labo.serendipityspot.auth

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.IntentSender
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CredentialManager
import androidx.credentials.CustomCredential
import androidx.credentials.GetCredentialRequest
import com.cloud42labo.serendipityspot.BuildConfig
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.libraries.identity.googleid.GetSignInWithGoogleOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.api.client.http.HttpRequestInitializer
import com.google.api.client.http.javanet.NetHttpTransport
import com.google.api.client.json.gson.GsonFactory
import com.google.api.services.drive.Drive
import com.google.api.services.drive.DriveScopes
import com.google.api.services.sheets.v4.Sheets
import com.google.api.services.sheets.v4.SheetsScopes
import kotlinx.coroutines.tasks.await

data class SignedInUser(val email: String, val displayName: String?)

sealed interface AuthorizationOutcome {
    data class Granted(val accessToken: String) : AuthorizationOutcome

    /** Sheets/Driveスコープがまだ許可されていない。この画面をユーザーに出す必要がある。 */
    data class ConsentRequired(val intentSender: IntentSender) : AuthorizationOutcome
}

/**
 * 認証（誰か）と認可（何をしてよいか）を分けて扱う。
 *
 *  - 認証: Credential Manager の Sign in with Google。旧 GoogleSignIn API は
 *    Googleがサポート終了を明示しているため使わない
 *  - 認可: AuthorizationClient で spreadsheets / drive.file スコープの
 *    アクセストークンを取る
 *
 * アクセストークンは1時間ほどで失効するので保持せず、必要になるたびに
 * [authorize] を呼ぶ。許可済みなら画面を出さずキャッシュ済みトークンが返る。
 */
class GoogleAuthManager(context: Context) {

    private val appContext = context.applicationContext
    private val credentialManager = CredentialManager.create(appContext)
    private val authorizationClient = Identity.getAuthorizationClient(appContext)

    suspend fun signIn(activity: Activity): SignedInUser {
        check(BuildConfig.GOOGLE_SERVER_CLIENT_ID.isNotBlank()) {
            "GOOGLE_SERVER_CLIENT_ID が未設定です。local.properties を確認してください"
        }

        val option = GetSignInWithGoogleOption.Builder(BuildConfig.GOOGLE_SERVER_CLIENT_ID).build()
        val request = GetCredentialRequest.Builder().addCredentialOption(option).build()

        val credential = credentialManager.getCredential(activity, request).credential
        check(
            credential is CustomCredential &&
                credential.type == GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL
        ) { "想定外の資格情報が返されました" }

        val googleIdToken = GoogleIdTokenCredential.createFrom(credential.data)
        return SignedInUser(email = googleIdToken.id, displayName = googleIdToken.displayName)
            .also { cacheUser(it) }
    }

    suspend fun signOut() {
        cacheUser(null)
        credentialManager.clearCredentialState(ClearCredentialStateRequest())
    }

    suspend fun authorize(): AuthorizationOutcome {
        val request = AuthorizationRequest.builder()
            .setRequestedScopes(REQUIRED_SCOPES)
            .build()
        return authorizationClient.authorize(request).await().toOutcome()
    }

    fun authorizationResultFrom(data: Intent?): AuthorizationOutcome =
        authorizationClient.getAuthorizationResultFromIntent(data).toOutcome()

    private fun AuthorizationResult.toOutcome(): AuthorizationOutcome {
        val sender = pendingIntent?.intentSender
        if (hasResolution() && sender != null) return AuthorizationOutcome.ConsentRequired(sender)
        val token = accessToken ?: error("アクセストークンを取得できませんでした")
        return AuthorizationOutcome.Granted(token)
    }

    fun sheetsService(accessToken: String): Sheets =
        Sheets.Builder(NetHttpTransport(), GsonFactory.getDefaultInstance(), bearer(accessToken))
            .setApplicationName(APP_NAME)
            .build()

    fun driveService(accessToken: String): Drive =
        Drive.Builder(NetHttpTransport(), GsonFactory.getDefaultInstance(), bearer(accessToken))
            .setApplicationName(APP_NAME)
            .build()

    private fun bearer(accessToken: String) = HttpRequestInitializer { request ->
        request.headers.authorization = "Bearer $accessToken"
    }

    fun cachedUser(): SignedInUser? {
        val prefs = appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val email = prefs.getString(KEY_EMAIL, null) ?: return null
        return SignedInUser(email, prefs.getString(KEY_DISPLAY_NAME, null))
    }

    private fun cacheUser(user: SignedInUser?) {
        appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().apply {
            if (user == null) {
                remove(KEY_EMAIL).remove(KEY_DISPLAY_NAME)
            } else {
                putString(KEY_EMAIL, user.email).putString(KEY_DISPLAY_NAME, user.displayName)
            }
        }.apply()
    }

    companion object {
        private const val APP_NAME = "Serendipity Spot"
        private const val PREFS = "serendipity_spot_auth"
        private const val KEY_EMAIL = "email"
        private const val KEY_DISPLAY_NAME = "display_name"

        private val REQUIRED_SCOPES = listOf(
            Scope(SheetsScopes.SPREADSHEETS),
            Scope(DriveScopes.DRIVE_FILE),
        )
    }
}
