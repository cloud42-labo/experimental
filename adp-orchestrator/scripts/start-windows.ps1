[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[CG][A-Z0-9]+$')]
    [string]$ControlChannelId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[CG][A-Z0-9]+$')]
    [string]$HumanRequestsChannelId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[CG][A-Z0-9]+$')]
    [string]$DailyChannelId,

    [ValidateRange(1, 86400)]
    [int]$LockLeaseSeconds = 3600,

    [ValidateNotNullOrEmpty()]
    [string]$PythonCommand = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($env:OS -ne 'Windows_NT') {
    throw 'This launcher requires Windows Credential Manager.'
}

if (-not ('AdpCredentialReader' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

public static class AdpCredentialReader
{
    private const uint CredentialTypeGeneric = 1;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Credential
    {
        public uint Flags;
        public uint Type;
        public IntPtr TargetName;
        public IntPtr Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public uint CredentialBlobSize;
        public IntPtr CredentialBlob;
        public uint Persist;
        public uint AttributeCount;
        public IntPtr Attributes;
        public IntPtr TargetAlias;
        public IntPtr UserName;
    }

    [DllImport("Advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CredRead(
        string target,
        uint type,
        uint reservedFlag,
        out IntPtr credentialPointer
    );

    [DllImport("Advapi32.dll", SetLastError = true)]
    private static extern void CredFree(IntPtr credentialPointer);

    public static string ReadGenericPassword(string target)
    {
        IntPtr credentialPointer;
        if (!CredRead(target, CredentialTypeGeneric, 0, out credentialPointer))
        {
            int errorCode = Marshal.GetLastWin32Error();
            throw new Win32Exception(errorCode, "Credential could not be read");
        }

        try
        {
            Credential credential = Marshal.PtrToStructure<Credential>(credentialPointer);
            if (credential.CredentialBlob == IntPtr.Zero || credential.CredentialBlobSize == 0)
            {
                return String.Empty;
            }

            int secretLength = checked((int)credential.CredentialBlobSize);
            byte[] secretBytes = new byte[secretLength];
            Marshal.Copy(credential.CredentialBlob, secretBytes, 0, secretBytes.Length);
            return Encoding.Unicode.GetString(secretBytes).TrimEnd('\0');
        }
        finally
        {
            CredFree(credentialPointer);
        }
    }
}
'@
}

function Get-AdpCredentialSecret {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetName
    )

    try {
        $secret = [AdpCredentialReader]::ReadGenericPassword($TargetName)
    }
    catch {
        throw "Windows credential '$TargetName' could not be read. Check that the Generic Credential exists."
    }

    if ([string]::IsNullOrWhiteSpace($secret)) {
        throw "Windows credential '$TargetName' has an empty password."
    }

    return $secret
}

$botToken = $null
$appToken = $null
$process = $null
$processInfo = $null
$exitCode = 1

try {
    $botToken = Get-AdpCredentialSecret -TargetName 'ADP_SLACK_BOT_TOKEN'
    $appToken = Get-AdpCredentialSecret -TargetName 'ADP_SLACK_APP_TOKEN'

    if (-not $botToken.StartsWith('xoxb-', [System.StringComparison]::Ordinal)) {
        throw "Windows credential 'ADP_SLACK_BOT_TOKEN' is not a Slack Bot Token."
    }
    if (-not $appToken.StartsWith('xapp-', [System.StringComparison]::Ordinal)) {
        throw "Windows credential 'ADP_SLACK_APP_TOKEN' is not a Slack App-Level Token."
    }

    $projectRoot = Split-Path -Parent $PSScriptRoot
    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $PythonCommand
    $processInfo.Arguments = '-m adp_orchestrator.app'
    $processInfo.WorkingDirectory = $projectRoot
    $processInfo.UseShellExecute = $false

    # Secrets exist only in this launcher process and the child Python process.
    # They are not written to .env, command-line arguments, logs, or Git.
    $processInfo.EnvironmentVariables['SLACK_BOT_TOKEN'] = $botToken
    $processInfo.EnvironmentVariables['SLACK_APP_TOKEN'] = $appToken
    $processInfo.EnvironmentVariables['ADP_CONTROL_CHANNEL_ID'] = $ControlChannelId
    $processInfo.EnvironmentVariables['ADP_HUMAN_REQUESTS_CHANNEL_ID'] = $HumanRequestsChannelId
    $processInfo.EnvironmentVariables['ADP_DAILY_CHANNEL_ID'] = $DailyChannelId
    $processInfo.EnvironmentVariables['ADP_LOCK_LEASE_SECONDS'] = [string]$LockLeaseSeconds

    $process = [System.Diagnostics.Process]::Start($processInfo)
    if ($null -eq $process) {
        throw 'The Orchestrator child process could not be started.'
    }

    $process.WaitForExit()
    $exitCode = $process.ExitCode
}
finally {
    if ($null -ne $processInfo) {
        [void]$processInfo.EnvironmentVariables.Remove('SLACK_BOT_TOKEN')
        [void]$processInfo.EnvironmentVariables.Remove('SLACK_APP_TOKEN')
    }
    $botToken = $null
    $appToken = $null
}

if ($exitCode -ne 0) {
    throw "ADP Orchestrator exited with code $exitCode."
}
