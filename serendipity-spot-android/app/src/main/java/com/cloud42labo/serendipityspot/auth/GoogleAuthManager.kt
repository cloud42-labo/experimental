package com.cloud42labo.serendipityspot.auth

import android.content.Context
import android.content.Intent
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInAccount
import com.google.android.gms.auth.api.signin.GoogleSignInClient
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.android.gms.common.api.Scope
import com.google.api.client.googleapis.extensions.android.gms.auth.GoogleAccountCredential
import com.google.api.client.http.javanet.NetHttpTransport
import com.google.api.client.json.gson.GsonFactory
import com.google.api.services.drive.Drive
import com.google.api.services.drive.DriveScopes
import com.google.api.services.sheets.v4.Sheets
import com.google.api.services.sheets.v4.SheetsScopes

/**
 * Googleサインインと、Sheets/Drive APIを呼ぶためのcredential生成をまとめる。
 *
 * 要求スコープは最小限にしている:
 *  - spreadsheets: このアプリが作った/開いたスプレッドシートの読み書き
 *  - drive.file: このアプリがDrive上で作成・開いたファイルだけにアクセス
 *    （ユーザーのDrive全体は見られない）
 */
class GoogleAuthManager(context: Context) {

    private val appContext = context.applicationContext

    val signInClient: GoogleSignInClient by lazy {
        val options = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            .requestEmail()
            .requestScopes(Scope(SheetsScopes.SPREADSHEETS))
            .requestScopes(Scope(DriveScopes.DRIVE_FILE))
            .build()
        GoogleSignIn.getClient(appContext, options)
    }

    fun signInIntent(): Intent = signInClient.signInIntent

    fun lastSignedInAccount(): GoogleSignInAccount? =
        GoogleSignIn.getLastSignedInAccount(appContext)

    fun signOut() {
        signInClient.signOut()
    }

    fun sheetsService(account: GoogleSignInAccount): Sheets {
        val credential = credentialFor(account)
        return Sheets.Builder(NetHttpTransport(), GsonFactory.getDefaultInstance(), credential)
            .setApplicationName(APP_NAME)
            .build()
    }

    fun driveService(account: GoogleSignInAccount): Drive {
        val credential = credentialFor(account)
        return Drive.Builder(NetHttpTransport(), GsonFactory.getDefaultInstance(), credential)
            .setApplicationName(APP_NAME)
            .build()
    }

    private fun credentialFor(account: GoogleSignInAccount): GoogleAccountCredential {
        val credential = GoogleAccountCredential.usingOAuth2(
            appContext,
            listOf(SheetsScopes.SPREADSHEETS, DriveScopes.DRIVE_FILE)
        )
        credential.selectedAccount = account.account
        return credential
    }

    companion object {
        private const val APP_NAME = "Serendipity Spot"
    }
}
