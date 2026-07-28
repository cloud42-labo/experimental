package com.cloud42labo.serendipityspot.data

import android.content.Context

/**
 * スプレッドシートの内容をローカルに1部だけキャッシュする。
 * 端末再起動直後、まだGoogleサインイン処理やネットワーク疎通が済んでいない
 * タイミングでもジオフェンスを再登録できるようにするための最小限のもの。
 * 正はあくまでスプレッドシート側で、これは復元用のキャッシュにすぎない。
 */
object SpotLocalCache {
    private const val PREFS = "serendipity_spot_cache"
    private const val KEY_SPOTS = "spots_json"
    private const val KEY_SPREADSHEET_ID = "spreadsheet_id"

    fun save(context: Context, spots: List<Spot>) {
        prefs(context).edit().putString(KEY_SPOTS, spots.toJson()).apply()
    }

    fun load(context: Context): List<Spot> {
        val json = prefs(context).getString(KEY_SPOTS, null) ?: return emptyList()
        return runCatching { json.toSpotList() }.getOrDefault(emptyList())
    }

    fun saveSpreadsheetId(context: Context, id: String) {
        prefs(context).edit().putString(KEY_SPREADSHEET_ID, id).apply()
    }

    fun loadSpreadsheetId(context: Context): String? =
        prefs(context).getString(KEY_SPREADSHEET_ID, null)

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
