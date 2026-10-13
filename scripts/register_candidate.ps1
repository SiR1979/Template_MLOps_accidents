#requires -Version 7.2
<#
.SYNOPSIS
Register the October 11 candidate once and verify one isolated local recovery.
.DESCRIPTION
Requires explicit authorization, the unpublished candidate-recovery branch and
the approved HEAD. Preserves every partial state on failure; never retries.
No training, deserialization, serving intervention, build, pull of images or Git publication.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$EvidenceDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\simon\MLOps_car_accident'
$store = 'C:\Users\simon\MLOps_car_accident_dvc_store'
$git = 'C:\Program Files\Git\cmd\git.exe'
$docker = 'C:\Users\simon\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe'
$head = '9f7028d9702f006159d8d68b067863f6db77a766'
$image = 'sha256:02d4a4e4c447f07446899843b89bb459edf6e79f561ccb8008974fccd1abbfb9'
$run = 'reference_20261011T144150Z_19d3274fd12e49d5b3cb9abbd73da5ea'
$invocation = '19d3274fd12e49d5b3cb9abbd73da5ea'
$mlflow = 'dcaea4d2f6ef4b3087f86e8bde3365d7'
$modelRelative = 'data/runs/' + $run + '/model/trained_model.joblib'
$sha = '9dcd169ed58e0b09a2367b17055abee4b7424741d1b02fa60aa196fe049f6b99'
$md5 = 'b2d9206c3d45a8c77599915c46e8cacb'
$pointer = 'versioning/candidate_20261011_19d3274f_model.dvc'
$manifest = 'versioning/candidate_20261011_19d3274f_manifest.json'
$registrar = Join-Path $root 'src/versioning/register_candidate.py'
$launcher = Join-Path $root 'scripts/register_candidate.ps1'
$protectedPngs = @(
    'assets/f916e28cbeb06964142cd5bd085b28290.png',
    'assets/f916e28cbeb06964142cd5bd085b28291.png',
    'assets/f916e28cbeb06964142cd5bd085b28292.png'
)
$script:records = [Collections.Generic.List[object]]::new()
$script:sequence = 0
$script:evidenceReady = $false
$report = [ordered]@{
    schema_name = 'candidate_recovery_execution_v1'
    request_classification = 'authorized_local_candidate_recovery_implementation'
    project_context = @{ project = 'car_accident'; root = $root; level_1 = 'NON_FINAL' }
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    status = 'running'
    approved_for_delivery = $false
    training_performed = $false
    model_deserialized = $false
    serving_services_changed = $false
    restoration_to_serving_path = $false
    files_changed = @('src/versioning/register_candidate.py','scripts/register_candidate.ps1',$pointer,$manifest,'docs/versioning.md')
    failure_policy = 'Preserve original error and all partial state; no cleanup or automatic replay.'
}

function Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Write-ExclusiveJson([string]$Path, $Value) {
    $text = ($Value | ConvertTo-Json -Depth 35) + [Environment]::NewLine
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
}

function Read-Json([string]$Path) {
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function File-Identity([string]$Path) {
    $item = Get-Item -LiteralPath $Path
    Assert (-not $item.PSIsContainer) ('Expected a file: ' + $Path)
    $current = $item
    while ($null -ne $current) {
        Assert (($current.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ('Linked path rejected: ' + $current.FullName)
        if ($current -is [IO.FileInfo]) { $current = $current.Directory }
        else { $current = $current.Parent }
    }
    return @{size_bytes = (Get-Item -LiteralPath $Path).Length; sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Native([string]$Label, [string]$Executable, [string[]]$Arguments, [switch]$RedactUrl) {
    $script:sequence++
    $record = [ordered]@{label=$Label; executable=$Executable; arguments=$Arguments; started_at_utc=[DateTime]::UtcNow.ToString('o'); exit_code=$null}
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Executable
    $info.WorkingDirectory = $root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    try {
        $null = $process.Start()
        $outTask = $process.StandardOutput.ReadToEndAsync()
        $errTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $outTask.GetAwaiter().GetResult()
        $stderr = $errTask.GetAwaiter().GetResult()
        if ($RedactUrl) {
            $stdout = [regex]::Replace($stdout, '(?<=://)[^/\s]*@', '[REDACTED]@')
            $stdout = [regex]::Replace($stdout, '[?#][^\s]*', '')
            $stderr = '[remote-query stderr withheld]'
        }
        $record.exit_code = $process.ExitCode
        $record.stdout = [string[]]@($stdout.Split([char]10) | ForEach-Object { $_.TrimEnd([char]13) } | Where-Object { $_.Length -gt 0 })
        $record.stderr = $stderr
    } catch {
        $record.error = $_.Exception.Message
        throw
    } finally {
        $record.finished_at_utc = [DateTime]::UtcNow.ToString('o')
        $script:records.Add([pscustomobject]$record)
        if ($script:evidenceReady) {
            Write-ExclusiveJson (Join-Path $EvidenceDirectory ('host_command_{0:d3}.json' -f $script:sequence)) $record
        }
        $process.Dispose()
    }
    Assert ($record.exit_code -eq 0) ('Command failed: ' + $Label + '; exit=' + $record.exit_code + '; ' + $record.stderr)
    return [pscustomobject]$record
}

function Git-Read([string]$Label, [string[]]$Arguments) {
    return Native $Label $git (@('--no-optional-locks','-C',$root) + $Arguments)
}

function Snapshot-Tree([string]$Directory) {
    $snapshot = @{}
    Assert (Test-Path -LiteralPath $Directory -PathType Container) ('Required directory is missing: ' + $Directory)
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Recurse -Force) {
        Assert (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) ('Linked storage entry rejected: ' + $item.FullName)
        if (-not $item.PSIsContainer) { $snapshot[[IO.Path]::GetRelativePath($Directory, $item.FullName)] = File-Identity $item.FullName }
    }
    return $snapshot
}

function Equal-Identity($Actual, $Expected) {
    return $Actual.sha256 -eq $Expected.sha256 -and $Actual.size_bytes -eq $Expected.size_bytes
}

function Check-Preserved($Snapshot, [string]$Base) {
    foreach ($name in $Snapshot.Keys) {
        Assert (Equal-Identity (File-Identity (Join-Path $Base $name)) $Snapshot[$name]) ('Preserved file changed: ' + $name)
    }
}

function Run-Phase([string]$Phase, [string]$Work, [bool]$StoreWritable) {
    $name = 'candidate-' + $Phase + '-' + ([IO.Path]::GetFileName($EvidenceDirectory) -split '_')[-1]
    $mounts = @(
        @{source=$Work; destination='/work'; writable=$true},
        @{source=(Join-Path $store 'objects'); destination='/store/objects'; writable=$StoreWritable},
        @{source=$registrar; destination='/opt/candidate/register_candidate.py'; writable=$false},
        @{source=(Join-Path $EvidenceDirectory 'context.json'); destination='/context.json'; writable=$false}
    )
    if ($Phase -eq 'registration') {
        $mounts += @{source=(Join-Path $root $modelRelative); destination=('/work/' + $modelRelative); writable=$false}
    }
    $arguments = @(
        'create','--name',$name,'--pull=never','--network=none','--read-only',
        '--cap-drop=ALL','--security-opt=no-new-privileges',
        '--tmpfs','/tmp:rw,nosuid,nodev','--tmpfs','/root:rw,nosuid,nodev',
        '--env','DVC_SITE_CACHE_DIR=/work/site-cache','--env','DVC_NO_ANALYTICS=1',
        '--workdir','/work'
    )
    foreach ($mount in $mounts) {
        $spec = 'type=bind,source=' + $mount.source + ',target=' + $mount.destination
        if (-not $mount.writable) { $spec += ',readonly' }
        $arguments += @('--mount',$spec)
    }
    $arguments += @($image,'python','-B','/opt/candidate/register_candidate.py',$Phase)
    $created = Native ($Phase + '_create') $docker $arguments
    Assert ($created.stdout.Count -eq 1 -and $created.stdout[0] -match '^[0-9a-f]{64}$') 'Container identity is not singular.'
    $containerId = $created.stdout[0]
    $format = '{"id":{{json .Id}},"image":{{json .Image}},"status":{{json .State.Status}},"exit_code":{{json .State.ExitCode}},"mounts":{{json .Mounts}},"network_mode":{{json .HostConfig.NetworkMode}},"readonly_rootfs":{{json .HostConfig.ReadonlyRootfs}},"cap_drop":{{json .HostConfig.CapDrop}},"security_opt":{{json .HostConfig.SecurityOpt}},"port_bindings":{{json .HostConfig.PortBindings}}}'
    $metadata = (Native ($Phase + '_mount_guard') $docker @('inspect','--type','container','--format',$format,$containerId)).stdout -join ''
    $observed = $metadata | ConvertFrom-Json
    Assert ($observed.image -eq $image -and $observed.status -eq 'created') 'Created container image/state differs.'
    $noPorts = $null -eq $observed.port_bindings -or @($observed.port_bindings.psobject.Properties).Count -eq 0
    Assert ($observed.network_mode -eq 'none' -and $observed.readonly_rootfs -and $noPorts) 'Container network/root boundary differs.'
    Assert (@($observed.cap_drop).Count -eq 1 -and $observed.cap_drop[0] -eq 'ALL' -and @($observed.security_opt).Count -eq 1 -and $observed.security_opt[0] -eq 'no-new-privileges') 'Container privilege boundary differs.'
    Assert (@($observed.mounts).Count -eq $mounts.Count) 'Unexpected container mount count.'
    foreach ($mount in $mounts) {
        $actual = @($observed.mounts | Where-Object { $_.Destination -eq $mount.destination })
        Assert ($actual.Count -eq 1 -and $actual[0].Type -eq 'bind' -and $actual[0].RW -eq $mount.writable) ('Mount boundary differs: ' + $mount.destination)
        $source = $actual[0].Source.Replace('\','/').ToLowerInvariant()
        $expected = $mount.source.Replace('\','/').ToLowerInvariant()
        Assert ($source -eq $expected) ('Mount source differs: ' + $mount.destination)
    }
    Write-ExclusiveJson (Join-Path $EvidenceDirectory ($Phase + '_container.json')) $observed
    $null = Native ($Phase + '_start_once') $docker @('start','--attach',$containerId)
    $final = (Native ($Phase + '_final_state') $docker @('inspect','--type','container','--format',$format,$containerId)).stdout -join ''
    $state = $final | ConvertFrom-Json
    Write-ExclusiveJson (Join-Path $EvidenceDirectory ($Phase + '_container_final.json')) $state
    Assert ($state.status -eq 'exited' -and $state.exit_code -eq 0) ('Container phase failed: ' + $Phase + '; exit=' + $state.exit_code)
    $result = Read-Json (Join-Path $Work 'phase_result.json')
    Assert ($result.status -eq 'passed' -and $result.actual_dvc_version -eq '3.67.1') ('Tool phase failed: ' + $Phase)
    return $result
}

try {
    $EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
    $prefix = [IO.Path]::GetFullPath((Join-Path $store 'validation')) + [IO.Path]::DirectorySeparatorChar
    Assert ($EvidenceDirectory.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) 'Evidence must stay within the approved store validation directory.'
    Assert ([IO.Path]::GetFileName($EvidenceDirectory) -match '^candidate_20261011_19d3274f_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{32}$') 'Unexpected evidence directory identity.'
    Assert (Test-Path -LiteralPath $EvidenceDirectory -PathType Container) 'Prepare a new evidence directory first.'
    Assert (-not (Test-Path -LiteralPath (Join-Path $EvidenceDirectory 'context.json'))) 'Existing attempt preserved; no replay.'
    Assert (Test-Path -LiteralPath (Join-Path $EvidenceDirectory 'original_versioning.md') -PathType Leaf) 'Original documentation backup is required.'
    $script:evidenceReady = $true
    $null = File-Identity (Join-Path $EvidenceDirectory 'original_versioning.md')
    $actualRoot = (Git-Read 'root' @('rev-parse','--show-toplevel')).stdout
    $actualHead = (Git-Read 'head' @('rev-parse','HEAD')).stdout
    $branch = (Git-Read 'branch' @('branch','--show-current')).stdout
    Assert ($actualRoot.Count -eq 1 -and $actualRoot[0].Replace('/','\') -eq $root) 'Repository root differs.'
    Assert ($actualHead.Count -eq 1 -and $actualHead[0] -eq $head) 'Approved HEAD differs.'
    Assert ($branch.Count -eq 1 -and $branch[0] -eq 'work/candidate-recovery') 'Unpublished candidate-recovery branch is required.'
    $index = (Git-Read 'index' @('diff','--cached','--name-only')).stdout
    Assert ($index.Count -eq 0) 'Existing staged changes preserved.'
    $dirty = (Git-Read 'tracked_changes' @('diff','--name-only')).stdout
    Assert ($dirty.Count -eq 1 -and $dirty[0] -eq 'docs/versioning.md') 'Unrelated tracked worktree changes preserved.'
    $untracked = (Git-Read 'untracked' @('ls-files','--others','--exclude-standard')).stdout
    $expectedUntracked = @($protectedPngs) + @('src/versioning/register_candidate.py','scripts/register_candidate.ps1')
    Assert (@(Compare-Object @($untracked | Sort-Object) @($expectedUntracked | Sort-Object)).Count -eq 0) 'Unexpected untracked scope preserved.'
    $origin = Native 'origin_redacted' $git @('--no-optional-locks','-C',$root,'remote','get-url','origin') -RedactUrl
    foreach ($target in @($pointer,$manifest)) { Assert (-not (Test-Path -LiteralPath (Join-Path $root $target))) ('Existing metadata preserved: ' + $target) }
    $modelIdentity = File-Identity (Join-Path $root $modelRelative)
    Assert ($modelIdentity.sha256 -eq $sha -and $modelIdentity.size_bytes -eq 107180009) 'Candidate byte identity differs.'
    Assert ((Get-FileHash -LiteralPath (Join-Path $root $modelRelative) -Algorithm MD5).Hash.ToLowerInvariant() -eq $md5) 'Candidate DVC identity differs.'
    $imageResult = (Native 'image_identity' $docker @('image','inspect','--format','{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}',$image)).stdout -join ''
    $imageInfo = $imageResult | ConvertFrom-Json
    Assert ($imageInfo.id -eq $image -and $imageInfo.os -eq 'linux' -and $imageInfo.architecture -eq 'amd64') 'Tool image identity differs.'
    $remoteObject = Join-Path $store ('objects/files/md5/' + $md5.Substring(0,2) + '/' + $md5.Substring(2))
    Assert (-not (Test-Path -LiteralPath $remoteObject)) 'Existing candidate object preserved; no replay.'

    $preserved = @{}
    $tracked = (Git-Read 'tracked_inventory' @('ls-files')).stdout
    foreach ($relative in $tracked) {
        if ($relative -ne 'docs/versioning.md') { $preserved[$relative] = File-Identity (Join-Path $root $relative) }
    }
    foreach ($relative in $protectedPngs) { $preserved[$relative] = File-Identity (Join-Path $root $relative) }
    $historical = Read-Json (Join-Path $root 'versioning/reference_manifest.json')
    foreach ($property in $historical.source_file_sha256.psobject.Properties) {
        $actual = File-Identity (Join-Path $root $property.Name)
        Assert (Equal-Identity $actual $property.Value) ('Historical source identity differs: ' + $property.Name)
        $preserved[$property.Name] = $actual
    }
    foreach ($property in $historical.metadata_file_sha256.psobject.Properties) {
        Assert ((File-Identity (Join-Path $root $property.Name)).sha256 -eq $property.Value) ('Historical pointer differs: ' + $property.Name)
    }
    foreach ($relative in @('.dvc/config.local','.dvcignore','src/versioning/register_candidate.py','scripts/register_candidate.ps1','docs/versioning.md')) {
        $preserved[$relative] = File-Identity (Join-Path $root $relative)
    }
    $runRoot = 'data/runs/' + $run
    $artifactManifest = Read-Json (Join-Path $root ($runRoot + '/tracking_evidence/artifact_manifest.json'))
    Assert ($artifactManifest.run_id -eq $run -and $artifactManifest.invocation_id -eq $invocation -and $artifactManifest.mlflow_run_id -eq $mlflow -and $artifactManifest.model_sha256 -eq $sha -and $artifactManifest.approved_for_delivery -eq $false) 'Historical artifact linkage differs.'
    foreach ($property in $artifactManifest.artifacts.psobject.Properties) {
        Assert ($property.Name.StartsWith('pipeline/') -and -not $property.Name.Contains('..')) 'Unexpected historical artifact path.'
        $relative = $property.Name.Substring('pipeline/'.Length)
        if ($relative.StartsWith('preprocessed/') -or $relative.StartsWith('model/') -or $relative -eq 'validation_report.json') {
            $relative = $runRoot + '/' + $relative
        } else { $relative = $runRoot + '/tracking_evidence/' + $relative }
        $actual = File-Identity (Join-Path $root $relative)
        Assert (Equal-Identity $actual $property.Value) ('Historical training artifact differs: ' + $relative)
        $preserved[$relative] = $actual
    }
    $receiptPaths = @(
        ($runRoot + '/validation_report.json'), ($runRoot + '/run_status.json'),
        ($runRoot + '/tracking_evidence/run_provenance.json'),
        ($runRoot + '/tracking_evidence/artifact_manifest.json'),
        ($runRoot + '/tracking_evidence/invocation_context.json'),
        'data/delivery_evidence/local_delivery_20261011T195239Z_19d3274fd12e49d5b3cb9abbd73da5ea/delivery.json'
    )
    $links = @{}
    foreach ($relative in $receiptPaths) {
        $links[$relative] = File-Identity (Join-Path $root $relative)
        $preserved[$relative] = $links[$relative]
    }
    $technical = Read-Json (Join-Path $root $receiptPaths[0])
    $status = Read-Json (Join-Path $root $receiptPaths[1])
    $provenance = Read-Json (Join-Path $root $receiptPaths[2])
    $invocationContext = Read-Json (Join-Path $root $receiptPaths[4])
    $delivery = Read-Json (Join-Path $root $receiptPaths[5])
    Assert ($technical.run_id -eq $run -and $technical.model_sha256 -eq $sha -and $technical.approved_for_delivery -eq $false) 'Technical receipt differs.'
    Assert ($status.status -eq 'completed' -and $status.approved_for_delivery -eq $false -and $status.tracking.invocation_id -eq $invocation -and $status.tracking.mlflow_run_id -eq $mlflow) 'Training status linkage differs.'
    Assert ($provenance.run_id -eq $run -and $provenance.invocation_id -eq $invocation -and $provenance.mlflow_run_id -eq $mlflow -and $provenance.model_sha256 -eq $sha -and $provenance.approved_for_delivery -eq $false) 'Training provenance differs.'
    Assert ($invocationContext.invocation_id -eq $invocation) 'Invocation receipt differs.'
    Assert ($delivery.candidate.sha256 -eq $sha -and $delivery.candidate.run_id -eq $run -and $delivery.candidate.invocation_id -eq $invocation -and $delivery.candidate.mlflow_run_id -eq $mlflow) 'Delivery receipt linkage differs.'
    $cacheBefore = Snapshot-Tree (Join-Path $root '.dvc/cache')
    $storeBefore = Snapshot-Tree (Join-Path $store 'objects')
    Write-ExclusiveJson (Join-Path $EvidenceDirectory 'preservation_before.json') @{repository_files=$preserved; primary_cache=$cacheBefore; existing_store_objects=$storeBefore}
    $context = @{
        schema_name='candidate_recovery_context_v1'; git_head=$head; branch=$branch[0]; image_id=$image
        origin_redacted=$origin.stdout; precheck_at_utc=[DateTime]::UtcNow.ToString('o')
        registrar_sha256=(File-Identity $registrar).sha256; launcher_sha256=(File-Identity $launcher).sha256
        linked_historical_evidence=$links; evidence_directory=$EvidenceDirectory; candidate=$modelIdentity
        authorization=@{
            source='Current human request: PLEASE IMPLEMENT THIS PLAN: Kandidaten-Recovery: Read-only-Befund und Minimalplan'
            scope='Unpublished local branch; five named repository files; additive local-store/cache/evidence writes; finite pinned tool containers; exactly one isolated recovery/hash check.'
            exclusions='Training, evaluation, model loading, serving changes, builds, image pulls, cleanup, staging, commits, pushes and public publication.'
        }
    }
    Write-ExclusiveJson (Join-Path $EvidenceDirectory 'context.json') $context
    $registration = Join-Path $EvidenceDirectory 'registration'
    $recovery = Join-Path $EvidenceDirectory 'recovery'
    Assert (-not (Test-Path -LiteralPath $registration) -and -not (Test-Path -LiteralPath $recovery)) 'Existing phase directories preserved; no replay.'
    $null = New-Item -ItemType Directory -Path $registration
    $null = New-Item -ItemType Directory -Path (Join-Path $registration ([IO.Path]::GetDirectoryName($modelRelative)))
    $report.registration = Run-Phase 'registration' $registration $true
    foreach ($relative in @($pointer,$manifest)) {
        Assert (-not (Test-Path -LiteralPath (Join-Path $root $relative))) ('Existing metadata preserved: ' + $relative)
        [IO.File]::Copy((Join-Path $registration $relative), (Join-Path $root $relative), $false)
    }
    $null = New-Item -ItemType Directory -Path $recovery
    Assert (@(Get-ChildItem -LiteralPath $recovery -Force).Count -eq 0) 'Recovery directory must initially be empty.'
    $null = New-Item -ItemType Directory -Path (Join-Path $recovery 'versioning')
    foreach ($relative in @($pointer,$manifest)) { [IO.File]::Copy((Join-Path $root $relative), (Join-Path $recovery $relative), $false) }
    $report.recovery = Run-Phase 'recovery' $recovery $false
    Assert ($report.recovery.dvc_pull_attempts -eq 1) 'Recovery pull count differs.'
    Assert (Equal-Identity (File-Identity (Join-Path $recovery $modelRelative)) $modelIdentity) 'Windows-host restored hash/size differs.'
    Check-Preserved $preserved $root
    Check-Preserved $cacheBefore (Join-Path $root '.dvc/cache')
    Check-Preserved $storeBefore (Join-Path $store 'objects')
    $cacheAfter = Snapshot-Tree (Join-Path $root '.dvc/cache')
    Assert (@(Compare-Object @($cacheBefore.Keys | Sort-Object) @($cacheAfter.Keys | Sort-Object)).Count -eq 0) 'Primary cache inventory changed.'
    $storeAfter = Snapshot-Tree (Join-Path $store 'objects')
    $addedObjects = @($storeAfter.Keys | Where-Object { -not $storeBefore.ContainsKey($_) })
    Assert ($addedObjects.Count -eq 1 -and $addedObjects[0].Replace('\','/') -eq ('files/md5/' + $md5.Substring(0,2) + '/' + $md5.Substring(2))) 'Unexpected new object-store scope.'
    Assert (Equal-Identity (File-Identity $remoteObject) $modelIdentity) 'Stored object host hash differs.'
    $finalHead = (Git-Read 'final_head' @('rev-parse','HEAD')).stdout
    $finalIndex = (Git-Read 'final_index' @('diff','--cached','--name-only')).stdout
    Assert ($finalHead.Count -eq 1 -and $finalHead[0] -eq $head -and $finalIndex.Count -eq 0) 'HEAD/index changed.'
    $finalStatus = (Git-Read 'final_status' @('status','--porcelain=v1','--untracked-files=all')).stdout
    $expectedStatus = @(' M docs/versioning.md') + @($protectedPngs + @('src/versioning/register_candidate.py','scripts/register_candidate.ps1',$pointer,$manifest) | ForEach-Object { '?? ' + $_ })
    Assert (@(Compare-Object @($finalStatus | Sort-Object) @($expectedStatus | Sort-Object)).Count -eq 0) 'Final worktree scope differs.'
    $report.preservation = @{repository_hashes='all_match'; primary_cache='unchanged'; existing_store_objects='all_match'; new_store_object_count=1; historical_approved_for_delivery=$false; git_head=$head; index='empty'; final_status=$finalStatus}
    $report.metadata = @{pointer=File-Identity (Join-Path $root $pointer); manifest=File-Identity (Join-Path $root $manifest)}
    $report.restored_model = @{host_path=(Join-Path $recovery $modelRelative); identity=File-Identity (Join-Path $recovery $modelRelative)}
    $report.status = 'passed_isolated_candidate_recovery'
    $report.remaining_todo_verify = @('Recovery does not establish model-quality acceptance, service readiness, external disaster recovery or Level 1 completion.')
} catch {
    $report.status = 'failed'
    $report.primary_error = $_.Exception.Message
    $report.failure_location = $_.InvocationInfo.PositionMessage
    $report.remaining_todo_verify = @('Preserve partial state. Diagnose the recorded failure before any separately authorized attempt.')
} finally {
    $report.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    $report.evidence_directory = $EvidenceDirectory
    if ($script:evidenceReady) {
        Write-ExclusiveJson (Join-Path $EvidenceDirectory 'command_records.json') $script:records.ToArray()
        Write-ExclusiveJson (Join-Path $EvidenceDirectory 'report.json') $report
    }
}
$report | ConvertTo-Json -Depth 20
if ($report.status -ne 'passed_isolated_candidate_recovery') { exit 1 }
