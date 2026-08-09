Set-StrictMode -Version 3.0

$script:NativeMenuSettleConsecutiveSamples = 40
$script:NativeMenuSettleMinimumSpanMilliseconds = 2000
$script:NativeMenuSettleTimeoutMilliseconds = 60000
$script:NativeMenuSettlePollMilliseconds = 55
$script:NativeMenuExtendedMinimumMilliseconds = 60000
$script:NativeMenuExtendedSpanMultiplier = 10
$script:NativeMenuExtendedMinimumSamples = 200
$script:NativeMenuExtendedPerSampleBudgetMilliseconds = 1000
$script:NativeMenuPopulationPhaseLimit = 4096
$script:NativeMenuActionDispatchTimeoutMilliseconds = 15000
$script:NativeMenuActionDispatchPollMilliseconds = 50

function Get-NativeMenuStringSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString(
            $algorithm.ComputeHash($bytes)
        ) -replace '-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function Assert-NativeMenuCaptureSurfaceAgreement {
    param(
        [Parameter(Mandatory = $true)][string]$OperatorScreenTag,
        [Parameter(Mandatory = $true)][string]$MachineClassifiedSurface
    )

    $captureSurface = Get-NativeMenuMachineSurfaceId `
        -ScreenTag $OperatorScreenTag
    if (
        $MachineClassifiedSurface -cne $captureSurface -and
        $MachineClassifiedSurface -cne $OperatorScreenTag
    ) {
        throw (
            "STOP: native-menu capture surface agreement rejected: " +
            "operator tag '$OperatorScreenTag' does not equal " +
            "machine-classified surface '$MachineClassifiedSurface' " +
            "through capture surface '$captureSurface'."
        )
    }
}

function Convert-NativeMenuBrowserTabToScreenTag {
    param([Parameter(Mandatory = $true)][string]$Tab)

    switch ($Tab) {
        "recent" { return "dark_cloud_recent" }
        "online_levels" { return "dark_cloud_online_levels" }
        "my_levels" { return "dark_cloud_my_levels" }
        default {
            throw "BROKEN: native-menu browser tab classifier returned '$Tab'."
        }
    }
}

function Test-NativeMenuScreenTagsEquivalent {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )

    if ($Left -ceq $Right) {
        return $true
    }
    $leftTab = Get-NativeMenuExpectedBrowserTab -ScreenTag $Left
    $rightTab = Get-NativeMenuExpectedBrowserTab -ScreenTag $Right
    return (
        -not [string]::IsNullOrWhiteSpace($leftTab) -and
        $leftTab -ceq $rightTab
    )
}

function Get-NativeMenuCaptureSurfaceId {
    param([Parameter(Mandatory = $true)][string]$ScreenTag)

    if ($ScreenTag -in @(
        "dark_cloud_browser",
        "dark_cloud_recent",
        "dark_cloud_online_levels",
        "dark_cloud_my_levels"
    )) {
        return "dark_cloud_browser"
    }
    if ($ScreenTag -in @(
        "hub_new_game",
        "hub_pristine_second_new_game",
        "hub_resumed"
    )) {
        return "hub"
    }
    return $ScreenTag
}

function Resolve-NativeMenuHubPathLayoutId {
    param([Parameter(Mandatory = $true)][object]$Layout)

    $elements = @($Layout.elements)
    $requiredLevelPickerArts = @(
        "LevelPicker.0",
        "LevelPicker.2",
        "LevelPicker.4",
        "LevelPicker.5",
        "LevelPicker.6"
    )
    $levelPickerCounts = [ordered]@{}
    foreach ($artId in $requiredLevelPickerArts) {
        $levelPickerCounts[$artId] = @($elements | Where-Object {
            [string]$_.kind -ceq "art" -and
            [string]$_.art_id -ceq $artId
        }).Count
    }
    $presentLevelPickerArts = @($requiredLevelPickerArts | Where-Object {
        [int]$levelPickerCounts[$_] -eq 1
    })
    $ambiguousLevelPickerArts = @($requiredLevelPickerArts | Where-Object {
        [int]$levelPickerCounts[$_] -gt 1
    })
    $ui28Count = @($elements | Where-Object {
        [string]$_.kind -ceq "art" -and
        [string]$_.art_id -ceq "UI.28"
    }).Count
    if ($ambiguousLevelPickerArts.Count -ne 0 -or $ui28Count -gt 1) {
        throw (
            "STOP: Hub path classifier found ambiguous path members: " +
            "LevelPicker='$($ambiguousLevelPickerArts -join ',')' " +
            "UI.28_count=$ui28Count."
        )
    }

    $layoutId = ""
    $requiredElementCount = 0
    if (
        $presentLevelPickerArts.Count -eq $requiredLevelPickerArts.Count -and
        $ui28Count -eq 1
    ) {
        $layoutId = "hub_pristine_second_new_game"
        $requiredElementCount = 15
    } elseif (
        $presentLevelPickerArts.Count -eq $requiredLevelPickerArts.Count -and
        $ui28Count -eq 0
    ) {
        $layoutId = "hub_new_game"
        $requiredElementCount = 14
    } elseif (
        $presentLevelPickerArts.Count -eq 0 -and
        $ui28Count -eq 1
    ) {
        $layoutId = "hub_resumed"
        $requiredElementCount = 10
    } else {
        throw (
            "STOP: Hub path classifier measured no exact authorized v2.13 " +
            "layout: UI.28_count=$ui28Count LevelPicker='" +
            ($presentLevelPickerArts -join ",") + "'."
        )
    }
    if ($elements.Count -ne $requiredElementCount) {
        throw (
            "STOP: Hub path classifier measured '$layoutId' with " +
            "$($elements.Count) members instead of its exact authorized " +
            "$requiredElementCount-member census."
        )
    }
    return $layoutId
}

function Get-NativeMenuMachineSurfaceId {
    param([Parameter(Mandatory = $true)][string]$ScreenTag)

    switch ($ScreenTag) {
        { $_ -in @("create_element", "create_discipline") } {
            return "create"
        }
        "beta_notice" { return "dialog" }
        { $_ -in @("pause_menu", "dark_cloud_menu") } {
            return "simple_menu"
        }
        "profile_save_select" { return "main_menu" }
        "dark_cloud_search" { return "quick_panel" }
        { $_ -in @(
            "dark_cloud_browser",
            "dark_cloud_recent",
            "dark_cloud_online_levels",
            "dark_cloud_my_levels",
            "dark_cloud_login_settings"
        ) } {
            return "dark_cloud_browser"
        }
        "dark_cloud_sort" { return "dark_cloud_sort" }
        "dark_cloud_options" { return "dark_cloud_options" }
        "skill_picker" { return "spell_picker" }
        { $_ -in @(
            "hub_new_game",
            "hub_pristine_second_new_game",
            "hub_resumed"
        ) } {
            return "hub"
        }
        default { return $ScreenTag }
    }
}

function Get-NativeMenuExpectedBrowserTab {
    param([Parameter(Mandatory = $true)][string]$ScreenTag)

    switch ($ScreenTag) {
        "dark_cloud_browser" { return "online_levels" }
        "dark_cloud_recent" { return "recent" }
        "dark_cloud_online_levels" { return "online_levels" }
        "dark_cloud_my_levels" { return "my_levels" }
        default { return "" }
    }
}

function Resolve-NativeMenuBrowserTabState {
    param([Parameter(Mandatory = $true)][object]$Layout)

    $tabActions = [ordered]@{
        recent = "dark_cloud_browser.recent"
        online_levels = "dark_cloud_browser.online_levels"
        my_levels = "dark_cloud_browser.my_levels"
    }
    $artElements = @($Layout.elements | Where-Object {
        [string]$_.kind -ceq "art" -and
        [string]$_.art_id -ceq "UI.13"
    })
    $measurements = [Collections.Generic.List[object]]::new()
    $geometryMembers = [Collections.Generic.List[object]]::new()
    foreach ($entry in $tabActions.GetEnumerator()) {
        $controls = @($Layout.elements | Where-Object {
            [string]$_.kind -ceq "control" -and
            [string]$_.action_id -ceq [string]$entry.Value
        })
        if ($controls.Count -ne 1) {
            throw (
                "STOP: native-menu browser tab verification could not resolve " +
                "exactly one '$($entry.Value)' control."
            )
        }
        $controlRect = @($controls[0].rect)
        if ($controlRect.Count -ne 4) {
            throw (
                "STOP: native-menu browser tab verification found a malformed " +
                "'$($entry.Value)' control rect."
            )
        }
        $leftMatches = @($artElements | Where-Object {
            $rect = @($_.rect)
            $rect.Count -eq 4 -and
            [double]$rect[0] -eq [double]$controlRect[0]
        })
        $rightMatches = @($artElements | Where-Object {
            $rect = @($_.rect)
            $rect.Count -eq 4 -and
            [double]$rect[2] -eq [double]$controlRect[2]
        })
        if ($leftMatches.Count -ne 1 -or $rightMatches.Count -ne 1) {
            throw (
                "STOP: native-menu browser tab verification did not resolve " +
                "one measured UI.13 bracket pair for '$($entry.Value)'."
            )
        }
        if ([string]$leftMatches[0].id -ceq [string]$rightMatches[0].id) {
            throw (
                "STOP: native-menu browser tab verification resolved one " +
                "UI.13 member as both sides of '$($entry.Value)'."
            )
        }
        $leftRect = @($leftMatches[0].rect)
        $rightRect = @($rightMatches[0].rect)
        if ([double]$leftRect[1] -ne [double]$rightRect[1]) {
            throw (
                "STOP: native-menu browser tab verification found a split " +
                "vertical bracket pair for '$($entry.Value)'."
            )
        }
        $geometryMembers.Add($leftMatches[0])
        $geometryMembers.Add($rightMatches[0])
        $measurements.Add([pscustomobject][ordered]@{
            tab = [string]$entry.Key
            action_id = [string]$entry.Value
            control_id = [string]$controls[0].id
            bracket_ids = @(
                [string]$leftMatches[0].id,
                [string]$rightMatches[0].id
            )
            bracket_top = [double]$leftRect[1]
            control_rect = @($controlRect | ForEach-Object { [double]$_ })
            bracket_rects = @(
                @($leftRect | ForEach-Object { [double]$_ }),
                @($rightRect | ForEach-Object { [double]$_ })
            )
        })
    }
    $memberIds = @($geometryMembers | ForEach-Object { [string]$_.id })
    if ($memberIds.Count -ne 6 -or @($memberIds | Sort-Object -Unique).Count -ne 6) {
        throw (
            "STOP: native-menu browser tab verification did not reach the " +
            "six distinct measured geometry-bearing bracket members."
        )
    }
    $minimumTop = ($measurements | Measure-Object -Property bracket_top -Minimum).Minimum
    $selected = @($measurements | Where-Object {
        [double]$_.bracket_top -eq [double]$minimumTop
    })
    $distinctTops = @(
        $measurements | ForEach-Object { [double]$_.bracket_top } |
            Sort-Object -Unique
    )
    if ($selected.Count -ne 1 -or $distinctTops.Count -ne 2) {
        throw (
            "STOP: native-menu browser tab verification did not resolve one " +
            "selected tab from the measured bracket geometry."
        )
    }
    $geometryJson = @($measurements) | ConvertTo-Json -Depth 20 -Compress
    return [pscustomobject][ordered]@{
        measured_tab = [string]$selected[0].tab
        member_ids = @($memberIds | Sort-Object)
        geometry_sha256 = Get-NativeMenuStringSha256 $geometryJson
        measurements = @($measurements)
    }
}

function Assert-NativeMenuBrowserTabAgreement {
    param(
        [Parameter(Mandatory = $true)][string]$OperatorScreenTag,
        [Parameter(Mandatory = $true)][object]$Layout
    )

    $expectedTab = Get-NativeMenuExpectedBrowserTab `
        -ScreenTag $OperatorScreenTag
    if ([string]::IsNullOrWhiteSpace($expectedTab)) {
        return $null
    }
    $measured = Resolve-NativeMenuBrowserTabState -Layout $Layout
    if ([string]$measured.measured_tab -cne $expectedTab) {
        throw (
            "STOP: native-menu browser tab agreement rejected: operator tag " +
            "'$OperatorScreenTag' requires tab '$expectedTab' but the six " +
            "measured geometry-bearing members classify " +
            "'$($measured.measured_tab)'."
        )
    }
    return [pscustomobject][ordered]@{
        expected_tab = $expectedTab
        measured_tab = [string]$measured.measured_tab
        member_ids = @($measured.member_ids)
        geometry_sha256 = [string]$measured.geometry_sha256
        measurements = @($measured.measurements)
    }
}

function Test-NativeMenuOwnedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable
    )

    $process = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    return (
        $null -ne $process -and
        $null -ne $process.ExecutablePath -and
        [string]::Equals(
            [IO.Path]::GetFullPath($process.ExecutablePath),
            $ExpectedExecutable,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Invoke-NativeMenuGit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $result = @(& git -C $Root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw (
            "BROKEN: git could not derive native-menu capture provenance: " +
            (($result | ForEach-Object { [string]$_ }) -join "`n")
        )
    }
    return (($result | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

function Get-NativeMenuProfileStateProvenance {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$InstanceRoot
    )

    $receiptPath = Join-Path $InstanceRoot (
        "stage\.sdmod\native-menu-profile-state.json"
    )
    $baselinePath = Join-Path $Root (
        "tests\fixtures\webgame\native-menu-profile-state-baseline.json"
    )
    $bindingContractPath = Join-Path $Root (
        "tests\fixtures\webgame\native-menu-hub-bindings-v213.json"
    )
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw (
            "BROKEN: the exact staged process has no pre-launch native-menu " +
            "profile-state receipt."
        )
    }
    if (-not (Test-Path -LiteralPath $baselinePath -PathType Leaf)) {
        throw "BROKEN: the pinned native-menu profile-state baseline is missing."
    }
    if (-not (Test-Path -LiteralPath $bindingContractPath -PathType Leaf)) {
        throw "BROKEN: the pinned native-menu per-binding baseline contract is missing."
    }
    try {
        $receipt = Get-Content -LiteralPath $receiptPath -Raw |
            ConvertFrom-Json
        $baseline = Get-Content -LiteralPath $baselinePath -Raw |
            ConvertFrom-Json
        $bindingContract = Get-Content -LiteralPath $bindingContractPath -Raw |
            ConvertFrom-Json
    } catch {
        throw "BROKEN: native-menu profile-state provenance is not valid JSON."
    }
    if (
        [string]$receipt.schema -cne
            "solomon-dark-native-menu-profile-state-v1" -or
        [string]$baseline.schema -cne
            "solomon-dark-native-menu-profile-state-baseline-v1" -or
        [string]$bindingContract.schema -cne
            "solomon-dark-native-menu-hub-bindings-v213" -or
        [string]$bindingContract.settlement_spec -cne "2.13" -or
        [bool]$bindingContract.baseline_legitimacy.copied_profile_state_forbidden `
            -ne $true
    ) {
        throw "BROKEN: native-menu profile-state provenance schema is not recognized."
    }
    $identity = [string]$receipt.profile_state_identity_sha256
    $freshBaseline = $bindingContract.baselines.pristine_fresh_install
    $derivedBaseline = $bindingContract.baselines.hub_new_game_two_action_v213
    $expectedIdentity = [string]$freshBaseline.profile_state_identity_sha256
    if ($identity -notmatch '^[0-9a-f]{64}$' -or
        $expectedIdentity -notmatch '^[0-9a-f]{64}$') {
        throw "BROKEN: native-menu profile-state identity is not a lowercase SHA-256."
    }
    $receiptFiles = @($receipt.files)
    $baselineFiles = @($baseline.profile_state.files)
    $baselineId = ""
    $witnessRole = ""
    $witnessInstance = ""
    $derivationEvidence = $null
    if ($identity -ceq $expectedIdentity) {
        $receiptFilesJson = $receiptFiles | ConvertTo-Json -Depth 20 -Compress
        $baselineFilesJson = $baselineFiles | ConvertTo-Json -Depth 20 -Compress
        if (
            [string]$receipt.baseline_mode -cne "fresh_install" -or
            [bool]$receipt.source_sandbox_excluded -ne $true -or
            [bool]$receipt.retail_appdata_seeded -ne $false -or
            [string]$baseline.profile_state.baseline_mode -cne "fresh_install" -or
            [bool]$baseline.profile_state.source_sandbox_excluded -ne $true -or
            [bool]$baseline.profile_state.retail_appdata_seeded -ne $false -or
            $receiptFilesJson -cne $baselineFilesJson -or
            $receiptFiles.Count -ne 0 -or
            $baselineFiles.Count -ne 0
        ) {
            throw (
                "STOP: native-menu profile-state provenance does not reproduce " +
                "the pinned pristine file-state contract."
            )
        }
        $baselineId = "pristine_fresh_install"
    } else {
        $witnesses = @($derivedBaseline.witnesses | Where-Object {
            [string]$_.profile_state_identity_sha256 -ceq $identity
        })
        if ($witnesses.Count -ne 1) {
            throw (
                "STOP: native-menu profile-state provenance mismatch: capture " +
                "identity '$identity' is not one exact pinned baseline witness."
            )
        }
        $instanceName = (Split-Path -Leaf $InstanceRoot).ToLowerInvariant()
        if ([string]$witnesses[0].instance -cne $instanceName) {
            throw (
                "STOP: native-menu derivation receipt mismatch: capture " +
                "instance '$instanceName' is not the pinned witness for " +
                "identity '$identity'."
            )
        }
        if (
            [string]$receipt.baseline_mode -cne "persistent_profile" -or
            [bool]$receipt.source_sandbox_excluded -ne $false -or
            [bool]$receipt.retail_appdata_seeded -ne $false -or
            $receiptFiles.Count -le 0
        ) {
            throw (
                "STOP: native-menu derivation receipt mismatch: capture did " +
                "not record the pinned derived durable files."
            )
        }
        $baselineId = "hub_new_game_two_action_v213"
        $witnessRole = [string]$witnesses[0].role
        $witnessInstance = [string]$witnesses[0].instance
        $derivationEvidence = [ordered]@{
            instance = $witnessInstance
            profile_state_receipt = $witnesses[0].profile_state_receipt
            potionguy_action_receipt = $witnesses[0].potionguy_action_receipt
            clean_completion_receipt = $witnesses[0].clean_completion_receipt
            settled_hub_observation = $witnesses[0].settled_hub_observation
        }
    }
    $baselineItem = Get-Item -LiteralPath $baselinePath
    $bindingContractItem = Get-Item -LiteralPath $bindingContractPath
    $receiptItem = Get-Item -LiteralPath $receiptPath
    $baselineFixture = if ($baselineId -ceq "pristine_fresh_install") {
        [ordered]@{
            repo_relative_path = (
                "tests/fixtures/webgame/" + $baselineItem.Name
            )
            sha256 = (Get-FileHash `
                -LiteralPath $baselineItem.FullName `
                -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $baselineItem.Length
        }
    } else {
        [ordered]@{
            repo_relative_path = (
                "tests/fixtures/webgame/" + $bindingContractItem.Name
            )
            sha256 = (Get-FileHash `
                -LiteralPath $bindingContractItem.FullName `
                -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $bindingContractItem.Length
        }
    }
    $value = [ordered]@{
        schema = [string]$receipt.schema
        profile_state_identity_sha256 = $identity
        baseline_id = $baselineId
        baseline_mode = [string]$receipt.baseline_mode
        source_sandbox_excluded = [bool]$receipt.source_sandbox_excluded
        retail_appdata_seeded = [bool]$receipt.retail_appdata_seeded
        durable_file_count = $receiptFiles.Count
        baseline_fixture = $baselineFixture
        binding_contract = [ordered]@{
            repo_relative_path = (
                "tests/fixtures/webgame/" + $bindingContractItem.Name
            )
            sha256 = (Get-FileHash `
                -LiteralPath $bindingContractItem.FullName `
                -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $bindingContractItem.Length
        }
        launch_receipt = [ordered]@{
            evidence_filename = $receiptItem.Name
            sha256 = (Get-FileHash `
                -LiteralPath $receiptItem.FullName `
                -Algorithm SHA256).Hash.ToLowerInvariant()
            bytes = $receiptItem.Length
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($witnessRole)) {
        $value["derivation_witness_role"] = $witnessRole
        $value["derivation_witness_instance"] = $witnessInstance
        $value["derivation_evidence"] = $derivationEvidence
    }
    return [pscustomobject]@{
        ReceiptPath = $receiptItem.FullName
        BindingContract = $bindingContract
        Value = $value
    }
}

function Get-NativeMenuProfileStateBinding {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [string]$LayoutId = "",
        [string]$EdgeId = ""
    )

    if ([string]::IsNullOrWhiteSpace($LayoutId) -eq
        [string]::IsNullOrWhiteSpace($EdgeId)) {
        throw "BROKEN: profile-state binding requires exactly one layout or edge id."
    }
    $baselineId = [string]$Context.ProfileState.baseline_id
    $requiredBaselineId = "pristine_fresh_install"
    $resolvedLayoutId = $LayoutId
    $pathDependentCore = $null
    if (-not [string]::IsNullOrWhiteSpace($LayoutId)) {
        $hubLayouts = @($Context.ProfileStateBindingContract.layouts.PSObject.Properties |
            Where-Object Name -ceq $LayoutId)
        if ($hubLayouts.Count -eq 1) {
            $hubLayout = $hubLayouts[0].Value
            $requiredBaselineId = [string]$hubLayout.required_baseline_id
            $pathDependentCore = [ordered]@{
                parent_screen_id = [string]$hubLayout.parent_screen_id
                path_qualifier = [string]$hubLayout.path_qualifier
                selector = [string]$hubLayout.selector
                required_baseline_id = [string]$hubLayout.required_baseline_id
                measured_settled_element_count = (
                    [int]$hubLayout.measured_settled_element_count
                )
                fork_decision = $hubLayout.fork_decision
            }
        } elseif ($hubLayouts.Count -gt 1) {
            throw "BROKEN: profile-state layout binding lookup is ambiguous."
        }
    } else {
        $hubBindings = @($Context.ProfileStateBindingContract.bindings |
            Where-Object {
                [string]$_.edge_id -ceq $EdgeId -and
                [string]$_.required_baseline_id -ceq $baselineId
            })
        $knownHubEdge = @($Context.ProfileStateBindingContract.bindings |
            Where-Object { [string]$_.edge_id -ceq $EdgeId })
        if ($knownHubEdge.Count -gt 0) {
            if ($hubBindings.Count -ne 1) {
                throw (
                    "STOP: native-menu per-binding profile-state baseline " +
                    "mismatch: edge '$EdgeId' has no unique binding for " +
                    "baseline '$baselineId'."
                )
            }
            $requiredBaselineId = [string]$hubBindings[0].required_baseline_id
            $resolvedLayoutId = [string]$hubBindings[0].layout_id
        }
    }
    if ($baselineId -cne $requiredBaselineId) {
        $bindingName = if (-not [string]::IsNullOrWhiteSpace($LayoutId)) {
            "layout '$LayoutId'"
        } else {
            "edge '$EdgeId'"
        }
        throw (
            "STOP: native-menu per-binding profile-state baseline mismatch: " +
            "$bindingName requires '$requiredBaselineId' but capture proves " +
            "'$baselineId'."
        )
    }
    $result = [ordered]@{
        baseline_id = $baselineId
        layout_id = $resolvedLayoutId
        edge_id = $EdgeId
        derivation_witness_role = [string]$(
            if ($Context.ProfileState.Contains("derivation_witness_role")) {
                $Context.ProfileState["derivation_witness_role"]
            } else { "" }
        )
    }
    if ($null -ne $pathDependentCore) {
        $result["path_dependent_core"] = $pathDependentCore
    }
    return $result
}

function Copy-NativeMenuProfileStateEvidence {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$DestinationDirectory,
        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')]
        [string]$EvidenceBasename
    )

    [IO.Directory]::CreateDirectory($DestinationDirectory) | Out-Null
    $destination = Join-Path $DestinationDirectory (
        $EvidenceBasename + ".profile-state.json"
    )
    if (Test-Path -LiteralPath $destination -PathType Leaf) {
        $existingSha = (
            Get-FileHash -LiteralPath $destination -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        if ($existingSha -cne
            [string]$Context.ProfileState.launch_receipt.sha256) {
            throw (
                "BROKEN: profile-state evidence filename is ambiguous for " +
                "'$EvidenceBasename'."
            )
        }
    } else {
        Copy-Item `
            -LiteralPath $Context.ProfileStateReceiptPath `
            -Destination $destination
    }
    $item = Get-Item -LiteralPath $destination
    $sha256 = (
        Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $sha256 -cne [string]$Context.ProfileState.launch_receipt.sha256 -or
        $item.Length -ne [long]$Context.ProfileState.launch_receipt.bytes
    ) {
        throw "BROKEN: copied profile-state evidence does not match the launch receipt."
    }
    $value = [ordered]@{}
    foreach ($property in $Context.ProfileState.GetEnumerator()) {
        if ([string]$property.Key -cne "launch_receipt") {
            $value[[string]$property.Key] = $property.Value
        }
    }
    $value["launch_receipt"] = [ordered]@{
        evidence_filename = $item.Name
        sha256 = $sha256
        bytes = $item.Length
    }
    return $value
}

function Assert-NativeMenuCaptureDriverQuiescent {
    param([Parameter(Mandatory = $true)][object]$Context)

    $result = Invoke-NativeMenuLua `
        -Context $Context `
        -LuaCode @'
return tostring(
  sd.runtime.get_environment_variable('SDMOD_UI_SANDBOX_PRESET') or ''
)
'@
    $preset = $result.Text.Trim()
    if ($preset -cne "idle") {
        throw (
            "STOP: native-menu capture driver quiescence rejected: " +
            "SDMOD_UI_SANDBOX_PRESET '$preset' is not the exact passive " +
            "'idle' preset."
        )
    }
    return $preset
}

function New-NativeMenuCaptureContext {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Instance,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )

    $instanceRoot = Join-Path $Root (
        "runtime\instances\" + $Instance.ToLowerInvariant()
    )
    $expectedExecutable = [IO.Path]::GetFullPath(
        (Join-Path $instanceRoot "stage\SolomonDark.exe")
    )
    $injectedLoader = [IO.Path]::GetFullPath(
        (Join-Path $Root "dist\launcher\SolomonDarkModLoader.dll")
    )
    if (-not (Test-NativeMenuOwnedProcess `
        -ProcessId $ProcessId `
        -ExpectedExecutable $expectedExecutable)) {
        throw "BROKEN: PID $ProcessId does not own the exact $Instance staged executable."
    }
    if (-not (Test-Path -LiteralPath $injectedLoader -PathType Leaf)) {
        throw "BROKEN: the repository launcher-side loader DLL is missing."
    }

    $baseCommitSha = Invoke-NativeMenuGit `
        -Root $Root `
        -Arguments @("rev-parse", "HEAD")
    if ($baseCommitSha -notmatch '^[0-9a-f]{40}$') {
        throw "BROKEN: git returned an invalid base commit for native-menu capture."
    }
    $sourceTreeSha = Invoke-NativeMenuGit `
        -Root $Root `
        -Arguments @("rev-parse", "HEAD^{tree}")
    if ($sourceTreeSha -notmatch '^[0-9a-f]{40}$') {
        throw "BROKEN: git returned an invalid source tree for native-menu capture."
    }
    $trackedChanges = Invoke-NativeMenuGit `
        -Root $Root `
        -Arguments @("status", "--porcelain", "--untracked-files=no")
    if (-not [string]::IsNullOrWhiteSpace($trackedChanges)) {
        throw (
            "BROKEN: native-menu capture requires a clean tracked tree so " +
            "base_commit_sha describes the running recorder."
        )
    }

    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonLauncher) {
        throw "BROKEN: py.exe is not available to run the Lua exec client."
    }
    $pythonProbe = @(& py.exe -3 -c "print('native-menu-python-ready')" 2>&1)
    if (
        $LASTEXITCODE -ne 0 -or
        (($pythonProbe | ForEach-Object { [string]$_ }) -join "`n").Trim() -ne
            "native-menu-python-ready"
    ) {
        throw "BROKEN: py.exe exists but cannot run the Python 3 Lua exec client."
    }

    $luaExecClient = Join-Path $Root "tools\lua-exec.py"
    if (-not (Test-Path -LiteralPath $luaExecClient -PathType Leaf)) {
        throw "BROKEN: the Lua exec client is missing from the capture tree."
    }
    $settlementClassifier = Join-Path $Root (
        "tools\native_menu_settlement_v2.py"
    )
    if (-not (Test-Path -LiteralPath $settlementClassifier -PathType Leaf)) {
        throw "BROKEN: the Settlement v2 classifier is missing from the capture tree."
    }
    $overlayReference = Join-Path $Root (
        "tests\fixtures\webgame\menu-overlay-reference.json"
    )
    if (-not (Test-Path -LiteralPath $overlayReference -PathType Leaf)) {
        throw "BROKEN: the machine-derived native-menu overlay reference is missing."
    }
    $startupLog = Join-Path $instanceRoot (
        "stage\.sdmod\logs\solomondarkmodloader.log"
    )
    if (-not (Test-Path -LiteralPath $startupLog -PathType Leaf)) {
        throw "BROKEN: the exact staged process has no loader startup log."
    }
    $captureHookReady = Select-String `
        -LiteralPath $startupLog `
        -SimpleMatch `
        -Quiet `
        -Pattern "Debug UI native menu-layout capture hooks installed."
    if (-not $captureHookReady) {
        throw (
            "BROKEN: the exact staged process did not install native menu-layout " +
            "capture hooks; launch it with SDMOD_NATIVE_MENU_LAYOUT_CAPTURE=1."
        )
    }

    $gameExecutableSha256 = (
        Get-FileHash -LiteralPath $expectedExecutable -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $loaderDllSha256 = (
        Get-FileHash -LiteralPath $injectedLoader -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $compatibilityPath = Join-Path $instanceRoot (
        "stage\.sdmod\multiplayer-compatibility.json"
    )
    if (-not (Test-Path -LiteralPath $compatibilityPath -PathType Leaf)) {
        throw "BROKEN: the staged launcher compatibility receipt is missing."
    }
    $compatibility = Get-Content -LiteralPath $compatibilityPath -Raw |
        ConvertFrom-Json
    if (
        [string]$compatibility.compatibility.gameExecutable.sha256 -ne
            $gameExecutableSha256 -or
        [string]$compatibility.compatibility.loader.sha256 -ne
            $loaderDllSha256
    ) {
        throw (
            "BROKEN: staged compatibility receipt does not identify the " +
            "exact game and launcher-side loader being hashed."
        )
    }

    $profileState = Get-NativeMenuProfileStateProvenance `
        -Root $Root `
        -InstanceRoot $instanceRoot

    $source = [ordered]@{
        base_commit_sha = $baseCommitSha
        source_tree_sha = $sourceTreeSha
        capture_tree = "exact committed tree at base_commit_sha"
        game_executable_sha256 = $gameExecutableSha256
        loader_dll_sha256 = $loaderDllSha256
        profile_state_identity_sha256 = (
            [string]$profileState.Value.profile_state_identity_sha256
        )
    }
    $context = [pscustomobject]@{
        Root = $Root
        Instance = $Instance
        ProcessId = $ProcessId
        ExpectedExecutable = $expectedExecutable
        InjectedLoader = $injectedLoader
        PipeName = "SolomonDarkModLoader_LuaExec_$Instance"
        LuaExecClient = $luaExecClient
        SettlementClassifier = $settlementClassifier
        OverlayReference = $overlayReference
        StartupLog = $startupLog
        Source = $source
        ProfileStateReceiptPath = $profileState.ReceiptPath
        ProfileState = $profileState.Value
        ProfileStateBindingContract = $profileState.BindingContract
    }
    $captureDriverPreset = Assert-NativeMenuCaptureDriverQuiescent `
        -Context $context
    $source["capture_driver_preset"] = $captureDriverPreset
    $context | Add-Member -NotePropertyName CaptureDriverPreset `
        -NotePropertyValue $captureDriverPreset
    return $context
}

function Assert-NativeMenuOverlayHygiene {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Layout
    )

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-overlay-hygiene-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $layoutPath = Join-Path $temporaryDirectory "layout.json"
    try {
        [IO.File]::WriteAllText(
            $layoutPath,
            (($Layout | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        $result = @(
            & py.exe -3 $Context.SettlementClassifier check-overlay `
                --layout $layoutPath `
                --reference $Context.OverlayReference 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($result | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = "STOP: native-menu overlay hygiene failed without diagnostics."
            }
            throw $message
        }
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Invoke-NativeMenuLua {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$LuaCode,
        [switch]$AllowBusy
    )

    $previousPipe = $env:SDMOD_LUA_EXEC_PIPE_NAME
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $Context.PipeName
        # Windows PowerShell promotes a native process's stderr to an
        # ErrorRecord.  Keep it in the merged result so the exit code and exact
        # text below can distinguish a contended pipe from a broken process.
        $ErrorActionPreference = "Continue"
        $result = @($LuaCode | & py.exe -3 $Context.LuaExecClient 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $previousPipe
        $ErrorActionPreference = $previousErrorActionPreference
    }
    $text = (($result | ForEach-Object { [string]$_ }) -join "`n").TrimEnd()
    if ($exitCode -eq 0) {
        return [pscustomobject]@{ Status = "ready"; Text = $text }
    }

    if (-not (Test-NativeMenuOwnedProcess `
        -ProcessId $Context.ProcessId `
        -ExpectedExecutable $Context.ExpectedExecutable)) {
        throw (
            "BROKEN: the exact staged process exited while the native-menu " +
            "recorder was waiting for Lua exec."
        )
    }
    $pipeUnavailable = (
        $text -match 'Cannot connect to pipe' -or
        $text -match 'timed out waiting for pipe' -or
        $text -match 'mod loader or Lua runtime may not be initialized yet'
    )
    if ($AllowBusy -and $pipeUnavailable) {
        return [pscustomobject]@{ Status = "busy"; Text = $text }
    }
    throw "BROKEN: Lua exec failed while the owned process remained alive: $text"
}

function Wait-NativeMenuActionDispatch {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][int]$RequestId,
        [Parameter(Mandatory = $true)][string]$ActionId,
        [Parameter(Mandatory = $true)][uint64]$SourceLayoutGeneration,
        [Parameter(Mandatory = $true)][string]$ExpectedDestinationScreen
    )

    $captureDestinationScreen = Get-NativeMenuMachineSurfaceId `
        -ScreenTag $ExpectedDestinationScreen
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $lastStatus = "not_ready"
    while ($clock.ElapsedMilliseconds -le
        $script:NativeMenuActionDispatchTimeoutMilliseconds) {
        $result = Invoke-NativeMenuLua `
            -Context $Context `
            -AllowBusy `
            -LuaCode @"
local function quote(value)
  value = tostring(value or '')
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return '"' .. value .. '"'
end
local dispatch = sd.ui.get_action_dispatch($RequestId)
local destination, capture_diagnostic =
  sd.ui.capture_current_layout([=[$captureDestinationScreen]=])
local classified_surface = type(destination) == 'table' and
  tostring(destination.screen_id or '') or
  (type(capture_diagnostic) == 'table' and
    tostring(capture_diagnostic.classified_screen_id or '') or '')
local layout_generation = type(destination) == 'table' and
  tonumber(destination.generation or 0) or 0
if type(dispatch) ~= 'table' then
  return table.concat({
    '{"status":"not_ready","error_message":"","classified_surface":',
    quote(classified_surface),
    ',"layout_generation":', tostring(layout_generation), '}'
  })
end
return table.concat({
  '{"status":', quote(dispatch.status),
  ',"error_message":', quote(dispatch.error_message),
  ',"classified_surface":', quote(classified_surface),
  ',"layout_generation":', tostring(layout_generation), '}'
})
"@
        if ($result.Status -eq "busy") {
            $lastStatus = "pipe_busy"
        } else {
            try {
                $dispatch = $result.Text | ConvertFrom-Json
            } catch {
                throw (
                    "BROKEN: native-menu action dispatch '$ActionId' returned " +
                    "invalid lifecycle JSON."
                )
            }
            $lastStatus = [string]$dispatch.status
            if ($lastStatus -ceq "dispatched") {
                return $dispatch
            }
            if (
                $lastStatus -ceq "dispatching" -and
                [string]$dispatch.classified_surface -ceq
                    $captureDestinationScreen -and
                [uint64]$dispatch.layout_generation -ne
                    $SourceLayoutGeneration
            ) {
                # Native modal handlers do not return until the modal closes.
                # Reaching the caller-pinned machine classification after the
                # layout generation advances proves the handler is runnable
                # without pretending that its lifecycle completed.
                return $dispatch
            }
            if ($lastStatus -ceq "failed") {
                throw (
                    "BROKEN: native-menu action dispatch '$ActionId' failed: " +
                    [string]$dispatch.error_message
                )
            }
            if ($lastStatus -notin @("not_ready", "queued", "dispatching")) {
                throw (
                    "BROKEN: native-menu action dispatch '$ActionId' reported " +
                    "unknown status '$lastStatus'."
                )
            }
        }
        Start-Sleep -Milliseconds `
            $script:NativeMenuActionDispatchPollMilliseconds
    }
    throw (
        "BROKEN: native-menu action dispatch '$ActionId' never became " +
        "runnable within $script:NativeMenuActionDispatchTimeoutMilliseconds " +
        "milliseconds; last_status='$lastStatus'."
    )
}

function Get-NativeMenuLayoutProbe {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [string]$FramePath = ""
    )

    $captureSurfaceId = Get-NativeMenuCaptureSurfaceId -ScreenTag $ScreenId
    $captureFrame = ""
    if (-not [string]::IsNullOrWhiteSpace($FramePath)) {
        $captureFrame = @"
local frame_ok, frame_message = sd.debug.capture_backbuffer([=[$FramePath]=])
if not frame_ok then error(tostring(frame_message)) end
"@
    }
    $lua = @"
local function quote(value)
  value = tostring(value or '')
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\b', '\\b')
  value = value:gsub('\f', '\\f')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return '"' .. value .. '"'
end
local function number(value)
  value = tonumber(value) or 0
  if value ~= value or value == math.huge or value == -math.huge then
    error('layout contains a non-finite number')
  end
  return string.format('%.6f', value)
end
local function boolean(value)
  return value and 'true' or 'false'
end
local function core(element)
  return table.concat({
    '{"id":', quote(element.id),
    ',"kind":', quote(element.kind),
    ',"text":', quote(element.text),
    ',"action_id":', quote(element.action_id),
    ',"art_id":', quote(element.art_id),
    ',"font_id":', quote(element.font_id),
    ',"text_style":', quote(element.text_style),
    ',"visible":', boolean(element.visible),
    ',"interactive":', boolean(element.interactive),
    ',"draw_order":', tostring(element.draw_order or 0)
  })
end
if type(sd) ~= 'table' or type(sd.ui) ~= 'table' or
    type(sd.ui.get_snapshot) ~= 'function' or
    type(sd.ui.capture_current_layout) ~= 'function' then
  return '__NATIVE_MENU_LAYOUT_NOT_READY__'
end
$captureFrame
local semantic = sd.ui.get_snapshot()
local snapshot, capture_diagnostic =
  sd.ui.capture_current_layout([=[$captureSurfaceId]=])
if type(snapshot) ~= 'table' then
  local classified = type(capture_diagnostic) == 'table' and
    tostring(capture_diagnostic.classified_screen_id or '') or ''
  if classified ~= '' then
    return table.concat({
      '__NATIVE_MENU_LAYOUT_SURFACE_MISMATCH__=' .. classified,
      tostring(semantic and semantic.surface_id or ''),
      tostring(semantic and semantic.generation or 0)
    }, '\t')
  end
  return '__NATIVE_MENU_LAYOUT_NOT_READY__'
end
local output = {
  '{',
  '"generation":' .. tostring(snapshot.generation or 0) .. ',',
  '"screen_id":' .. quote(snapshot.screen_id) .. ',',
  '"screen_title":' .. quote(snapshot.screen_title) .. ',',
  '"capture_method":' .. quote(snapshot.capture_method) .. ',',
  '"elements":['
}
local structure = {
  '{',
  '"generation":' .. tostring(snapshot.generation or 0) .. ',',
  '"screen_id":' .. quote(snapshot.screen_id) .. ',',
  '"screen_title":' .. quote(snapshot.screen_title) .. ',',
  '"capture_method":' .. quote(snapshot.capture_method) .. ',',
  '"elements":['
}
for index, element in ipairs(snapshot.elements or {}) do
  if index > 1 then
    output[#output + 1] = ','
  end
  output[#output + 1] = core(element) .. table.concat({
    ',"rect":[', number(element.left), ',', number(element.top), ',',
      number(element.right), ',', number(element.bottom), ']',
    ',"unclipped_rect":[', number(element.unclipped_left), ',',
      number(element.unclipped_top), ',', number(element.unclipped_right),
      ',', number(element.unclipped_bottom), ']}'
  })
end
local structural_elements = {}
for index, element in ipairs(snapshot.elements or {}) do
  structural_elements[index] = element
end
table.sort(structural_elements, function(left, right)
  local left_order = tonumber(left.draw_order) or 0
  local right_order = tonumber(right.draw_order) or 0
  if left_order ~= right_order then return left_order < right_order end
  return tostring(left.id or '') < tostring(right.id or '')
end)
for index, element in ipairs(structural_elements) do
  if index > 1 then structure[#structure + 1] = ',' end
  structure[#structure + 1] = core(element) .. '}'
end
output[#output + 1] = ']}'
structure[#structure + 1] = ']}'
return table.concat({
  '__SURFACE__=' .. tostring(snapshot.screen_id or ''),
  '__SEMANTIC_GENERATION__=' .. tostring(snapshot.generation or 0),
  '__NATIVE_SURFACE__=' .. tostring(semantic and semantic.surface_id or ''),
  '__NATIVE_GENERATION__=' .. tostring(semantic and semantic.generation or 0),
  '__CAPTURED_AT__=' .. tostring(snapshot.captured_at_milliseconds or 0),
  '__STRUCTURE__=' .. table.concat(structure),
  '__PAYLOAD__=' .. table.concat(output)
}, '\n')
"@
    $result = Invoke-NativeMenuLua `
        -Context $Context `
        -LuaCode $lua `
        -AllowBusy
    if ($result.Status -eq "busy") {
        return [pscustomobject]@{ Status = "busy"; Detail = $result.Text }
    }
    if ($result.Text -eq "__NATIVE_MENU_LAYOUT_NOT_READY__") {
        return [pscustomobject]@{
            Status = "not_ready"
            Detail = "capture_current_layout returned no current frame"
        }
    }
    if ($result.Text.StartsWith(
        "__NATIVE_MENU_LAYOUT_SURFACE_MISMATCH__="
    )) {
        $mismatchFields = @($result.Text.Substring(
            "__NATIVE_MENU_LAYOUT_SURFACE_MISMATCH__=".Length
        ) -split "`t", 3)
        if ($mismatchFields.Count -ne 3) {
            throw "BROKEN: malformed native-menu surface mismatch diagnostic."
        }
        $machineSurface = $mismatchFields[0]
        try {
            Assert-NativeMenuCaptureSurfaceAgreement `
                -OperatorScreenTag $ScreenId `
                -MachineClassifiedSurface $machineSurface
        } catch {
            return [pscustomobject]@{
                Status = "wrong_surface"
                Detail = [string]$_.Exception.Message
                SemanticSurface = $machineSurface
                NativeSurface = $mismatchFields[1]
                NativeGeneration = [uint64]$mismatchFields[2]
            }
        }
        return [pscustomobject]@{
            Status = "not_ready"
            Detail = (
                "machine-classified surface '$machineSurface' reached the " +
                "expected logical layout, but its exact capture snapshot " +
                "is still populating"
            )
            SemanticSurface = $machineSurface
            MachineClassifiedSurface = $machineSurface
            NativeSurface = $mismatchFields[1]
            NativeGeneration = [uint64]$mismatchFields[2]
        }
    }
    $parts = @($result.Text -split "`r?`n", 7)
    if (
        $parts.Count -ne 7 -or
        -not $parts[0].StartsWith("__SURFACE__=") -or
        -not $parts[1].StartsWith("__SEMANTIC_GENERATION__=") -or
        -not $parts[2].StartsWith("__NATIVE_SURFACE__=") -or
        -not $parts[3].StartsWith("__NATIVE_GENERATION__=") -or
        -not $parts[4].StartsWith("__CAPTURED_AT__=") -or
        -not $parts[5].StartsWith("__STRUCTURE__=") -or
        -not $parts[6].StartsWith("__PAYLOAD__=")
    ) {
        throw "BROKEN: malformed native-menu semantic probe: $($result.Text)"
    }
    $nonGeometryJson = $parts[5].Substring("__STRUCTURE__=".Length)
    $semanticJson = $parts[6].Substring("__PAYLOAD__=".Length)
    try {
        $semanticPayload = $semanticJson | ConvertFrom-Json
    } catch {
        throw "BROKEN: native-menu semantic probe returned invalid JSON: $semanticJson"
    }
    $machineSurface = $parts[0].Substring("__SURFACE__=".Length)
    Assert-NativeMenuCaptureSurfaceAgreement `
        -OperatorScreenTag $ScreenId `
        -MachineClassifiedSurface $machineSurface
    $browserTabVerification = $null
    $expectedBrowserTab = Get-NativeMenuExpectedBrowserTab `
        -ScreenTag $ScreenId
    if (-not [string]::IsNullOrWhiteSpace($expectedBrowserTab)) {
        try {
            $browserTabVerification = Assert-NativeMenuBrowserTabAgreement `
                -OperatorScreenTag $ScreenId `
                -Layout $semanticPayload
        } catch {
            $measured = Resolve-NativeMenuBrowserTabState -Layout $semanticPayload
            return [pscustomobject]@{
                Status = "wrong_tab"
                Detail = [string]$_.Exception.Message
                SemanticSurface = Convert-NativeMenuBrowserTabToScreenTag `
                    -Tab ([string]$measured.measured_tab)
                MachineClassifiedSurface = $machineSurface
                NativeSurface = $parts[2].Substring("__NATIVE_SURFACE__=".Length)
                NativeGeneration = [uint64]$parts[3].Substring(
                    "__NATIVE_GENERATION__=".Length
                )
                BrowserTabVerification = $measured
            }
        }
        if ($ScreenId -cne $captureSurfaceId) {
            $from = '"screen_id":"' + $captureSurfaceId + '"'
            $to = '"screen_id":"' + $ScreenId + '"'
            if (
                ([regex]::Matches(
                    $semanticJson,
                    [regex]::Escape($from)
                )).Count -ne 1 -or
                ([regex]::Matches(
                    $nonGeometryJson,
                    [regex]::Escape($from)
                )).Count -ne 1
            ) {
                throw (
                    "BROKEN: browser tab verification could not re-tag one " +
                    "machine-classified semantic payload."
                )
            }
            $semanticJson = $semanticJson.Replace($from, $to)
            $nonGeometryJson = $nonGeometryJson.Replace($from, $to)
            $semanticPayload.screen_id = $ScreenId
        }
    }
    if (
        $captureSurfaceId -ceq "hub" -and
        $ScreenId -cne $captureSurfaceId
    ) {
        try {
            $measuredHubLayout = Resolve-NativeMenuHubPathLayoutId `
                -Layout $semanticPayload
        } catch {
            return [pscustomobject]@{
                Status = "wrong_surface"
                Detail = [string]$_.Exception.Message
                SemanticSurface = $machineSurface
                MachineClassifiedSurface = $machineSurface
                NativeSurface = $parts[2].Substring("__NATIVE_SURFACE__=".Length)
                NativeGeneration = [uint64]$parts[3].Substring(
                    "__NATIVE_GENERATION__=".Length
                )
            }
        }
        if ($measuredHubLayout -cne $ScreenId) {
            return [pscustomobject]@{
                Status = "wrong_surface"
                Detail = (
                    "STOP: Hub path selector expected '$ScreenId' but " +
                    "machine-classified '$measuredHubLayout'."
                )
                SemanticSurface = $measuredHubLayout
                MachineClassifiedSurface = $machineSurface
                NativeSurface = $parts[2].Substring("__NATIVE_SURFACE__=".Length)
                NativeGeneration = [uint64]$parts[3].Substring(
                    "__NATIVE_GENERATION__=".Length
                )
            }
        }
        $from = '"screen_id":"hub"'
        $to = '"screen_id":"' + $ScreenId + '"'
        if (
            ([regex]::Matches(
                $semanticJson,
                [regex]::Escape($from)
            )).Count -ne 1 -or
            ([regex]::Matches(
                $nonGeometryJson,
                [regex]::Escape($from)
            )).Count -ne 1
        ) {
            throw (
                "BROKEN: Hub path classifier could not re-tag one exact " +
                "machine-classified semantic payload."
            )
        }
        $semanticJson = $semanticJson.Replace($from, $to)
        $nonGeometryJson = $nonGeometryJson.Replace($from, $to)
        $semanticPayload.screen_id = $ScreenId
    }
    return [pscustomobject]@{
        Status = "ready"
        SemanticSurface = $ScreenId
        MachineClassifiedSurface = $machineSurface
        SemanticGeneration = [uint64]$parts[1].Substring(
            "__SEMANTIC_GENERATION__=".Length
        )
        NativeSurface = $parts[2].Substring("__NATIVE_SURFACE__=".Length)
        NativeGeneration = [uint64]$parts[3].Substring(
            "__NATIVE_GENERATION__=".Length
        )
        CapturedAtMilliseconds = [uint64]$parts[4].Substring(
            "__CAPTURED_AT__=".Length
        )
        NonGeometryJson = $nonGeometryJson
        SemanticJson = $semanticJson
        SemanticPayload = $semanticPayload
        BrowserTabVerification = $browserTabVerification
    }
}

function Initialize-NativeMenuPopulationSampler {
    param([Parameter(Mandatory = $true)][object]$Context)

    $result = Invoke-NativeMenuLua -Context $Context -LuaCode @"
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then
  sampler = {
    active = false,
    by_structure = {},
    phases = {},
    sample_count = 0,
    overflow = false,
    error = ''
  }
  rawset(_G, '__sd_native_menu_population_sampler', sampler)
  local function quote(value)
    value = tostring(value or '')
    value = value:gsub('\\', '\\\\')
    value = value:gsub('"', '\\"')
    value = value:gsub('\b', '\\b')
    value = value:gsub('\f', '\\f')
    value = value:gsub('\n', '\\n')
    value = value:gsub('\r', '\\r')
    value = value:gsub('\t', '\\t')
    return '"' .. value .. '"'
  end
  local function boolean(value)
    return value and 'true' or 'false'
  end
  local function core(element)
    return table.concat({
      '{"id":', quote(element.id),
      ',"kind":', quote(element.kind),
      ',"text":', quote(element.text),
      ',"action_id":', quote(element.action_id),
      ',"art_id":', quote(element.art_id),
      ',"font_id":', quote(element.font_id),
      ',"text_style":', quote(element.text_style),
      ',"visible":', boolean(element.visible),
      ',"interactive":', boolean(element.interactive),
      ',"draw_order":', tostring(element.draw_order or 0)
    })
  end
  local function compact(element)
    return table.concat({
      '[', quote(element.id),
      ',', quote(element.kind),
      ',', quote(element.text),
      ',', quote(element.action_id),
      ',', quote(element.art_id),
      ',', quote(element.font_id),
      ',', quote(element.text_style),
      ',', boolean(element.visible),
      ',', boolean(element.interactive),
      ',', tostring(element.draw_order or 0),
      ',[', tostring(element.left or 0), ',', tostring(element.top or 0),
      ',', tostring(element.right or 0), ',', tostring(element.bottom or 0), ']',
      ',[', tostring(element.unclipped_left or 0),
      ',', tostring(element.unclipped_top or 0),
      ',', tostring(element.unclipped_right or 0),
      ',', tostring(element.unclipped_bottom or 0), ']]'
    })
  end
  sd.events.on('runtime.tick', function(event)
    local state = rawget(_G, '__sd_native_menu_population_sampler')
    if state == nil or not state.active then return end
    local ok, detail = pcall(function()
      local snapshot = sd.ui.capture_current_layout(state.capture_screen_id)
      if type(snapshot) ~= 'table' then return end
      snapshot.screen_id = state.logical_screen_id
      local structural_elements = {}
      for index, element in ipairs(snapshot.elements or {}) do
        structural_elements[index] = element
      end
      table.sort(structural_elements, function(left, right)
        local left_order = tonumber(left.draw_order) or 0
        local right_order = tonumber(right.draw_order) or 0
        if left_order ~= right_order then return left_order < right_order end
        return tostring(left.id or '') < tostring(right.id or '')
      end)
      local structure_elements = {}
      for index, element in ipairs(structural_elements) do
        structure_elements[index] = core(element) .. '}'
      end
      local payload_elements = {}
      for index, element in ipairs(snapshot.elements or {}) do
        payload_elements[index] = compact(element)
      end
      local prefix = table.concat({
        '{"generation":', tostring(snapshot.generation or 0),
        ',"screen_id":', quote(snapshot.screen_id),
        ',"screen_title":', quote(snapshot.screen_title),
        ',"capture_method":', quote(snapshot.capture_method),
        ',"elements":['
      })
      local structure = prefix .. table.concat(structure_elements, ',') .. ']}'
      local payload = prefix .. table.concat(payload_elements, ',') .. ']}'
      local now = tonumber(event and event.monotonic_milliseconds) or 0
      state.sample_count = state.sample_count + 1
      local phase_index = state.by_structure[structure]
      if phase_index ~= nil then
        local phase = state.phases[phase_index]
        phase.last_seen_milliseconds = now
        phase.observations = phase.observations + 1
        return
      end
      if #state.phases >= $script:NativeMenuPopulationPhaseLimit then
        state.overflow = true
        state.active = false
        return
      end
      state.phases[#state.phases + 1] = {
        first_seen_milliseconds = now,
        last_seen_milliseconds = now,
        observations = 1,
        payload_json = payload
      }
      state.by_structure[structure] = #state.phases
    end)
    if not ok then
      state.error = tostring(detail)
      state.active = false
    end
  end)
end
return 'population-sampler-ready'
"@
    if ($result.Text.Trim() -ne "population-sampler-ready") {
        throw "BROKEN: native-menu population sampler did not initialize."
    }
}

function Start-NativeMenuPopulationSampler {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId
    )

    $captureSurfaceId = Get-NativeMenuCaptureSurfaceId -ScreenTag $ScreenId
    $result = Invoke-NativeMenuLua -Context $Context -LuaCode @"
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then error('population sampler was not initialized') end
sampler.active = false
sampler.by_structure = {}
sampler.phases = {}
sampler.sample_count = 0
sampler.overflow = false
sampler.error = ''
sampler.capture_screen_id = [=[$captureSurfaceId]=]
sampler.logical_screen_id = [=[$ScreenId]=]
sampler.active = true
return 'population-sampler-armed'
"@
    if ($result.Text.Trim() -ne "population-sampler-armed") {
        throw "BROKEN: native-menu population sampler did not arm."
    }
}

function Stop-NativeMenuPopulationSampler {
    param([Parameter(Mandatory = $true)][object]$Context)

    $result = Invoke-NativeMenuLua -Context $Context -LuaCode @'
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then error('population sampler was not initialized') end
sampler.active = false
local function quote(value)
  value = tostring(value or '')
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return '"' .. value .. '"'
end
return table.concat({
  '{"sample_count":', tostring(sampler.sample_count or 0),
  ',"overflow":', sampler.overflow and 'true' or 'false',
  ',"error":', quote(sampler.error),
  ',"phase_count":', tostring(#(sampler.phases or {})), '}'
})
'@
    try {
        $metadata = $result.Text | ConvertFrom-Json
    } catch {
        throw "BROKEN: native-menu population sampler returned invalid metadata."
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$metadata.error)) {
        throw "BROKEN: native-menu population sampler failed: $($metadata.error)"
    }
    if ([bool]$metadata.overflow) {
        throw (
            "STOP: native-menu population sampler exceeded " +
            "$script:NativeMenuPopulationPhaseLimit structural phases."
        )
    }
    $phaseCount = [int]$metadata.phase_count
    if ([int]$metadata.sample_count -le 0 -or $phaseCount -le 0) {
        throw "STOP: native-menu population sampler observed no destination phase."
    }
    if ($phaseCount -gt $script:NativeMenuPopulationPhaseLimit) {
        throw "BROKEN: native-menu population phase count exceeded its declared limit."
    }

    $phases = [Collections.Generic.List[object]]::new()
    try {
        for ($phaseIndex = 1; $phaseIndex -le $phaseCount; $phaseIndex++) {
            $phaseResult = Invoke-NativeMenuLua -Context $Context -LuaCode @"
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then error('population sampler was not initialized') end
local phase = (sampler.phases or {})[$phaseIndex]
if phase == nil then error('population sampler phase is absent') end
return table.concat({
  '{"first_seen_milliseconds":',
    tostring(phase.first_seen_milliseconds or 0),
  ',"last_seen_milliseconds":',
    tostring(phase.last_seen_milliseconds or 0),
  ',"observations":', tostring(phase.observations or 0),
  ',"payload_encoding":"structural-element-arrays-v1"',
  ',"payload":', phase.payload_json, '}'
})
"@
            try {
                $phases.Add(($phaseResult.Text | ConvertFrom-Json))
            } catch {
                throw (
                    "BROKEN: native-menu population sampler phase " +
                    "$phaseIndex returned invalid JSON."
                )
            }
        }
    } finally {
        Invoke-NativeMenuLua -Context $Context -LuaCode @'
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler ~= nil then
  sampler.by_structure = {}
  sampler.phases = {}
end
return 'population-sampler-released'
'@ | Out-Null
    }

    return [pscustomobject]@{
        sample_count = [int]$metadata.sample_count
        overflow = $false
        error = ""
        structural_phases = @($phases)
    }
}

function Invoke-NativeMenuSettlementClassifier {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object[]]$Samples
    )

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-settlement-v2-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $inputPath = Join-Path $temporaryDirectory "samples.json"
    $outputPath = Join-Path $temporaryDirectory "classification.json"
    try {
        [IO.File]::WriteAllText(
            $inputPath,
            (($Samples | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        $classifierOutput = @(
            & py.exe -3 $Context.SettlementClassifier find `
                --input $inputPath `
                --output $outputPath 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($classifierOutput | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = "Settlement v2.9 classifier exited without diagnostics."
            }
            throw $message
        }
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "BROKEN: Settlement v2.9 classifier produced no result."
        }
        return Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Invoke-NativeMenuExtendedObservationClassifier {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object[]]$Samples,
        [Parameter(Mandatory = $true)][long]$RequiredSpanMilliseconds
    )

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-motion-v23-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $inputPath = Join-Path $temporaryDirectory "samples.json"
    $outputPath = Join-Path $temporaryDirectory "classification.json"
    try {
        [IO.File]::WriteAllText(
            $inputPath,
            (($Samples | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        $classifierOutput = @(
            & py.exe -3 $Context.SettlementClassifier classify-extended `
                --input $inputPath `
                --output $outputPath `
                --required-span-milliseconds $RequiredSpanMilliseconds 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($classifierOutput | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = (
                    "Settlement v2.3 extended classifier exited without diagnostics."
                )
            }
            throw $message
        }
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "BROKEN: Settlement v2.3 extended classifier produced no result."
        }
        return Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Wait-NativeMenuLayoutSettlement {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$LatencyClock,
        [string]$TransitionalSourceScreen = ""
    )

    $sampleCount = 0
    $busyCount = 0
    $notReadyCount = 0
    $lastUnavailable = ""
    $lastRejectedCandidate = ""
    $structuralPhaseOrder = [Collections.Generic.List[string]]::new()
    $structuralPhaseByHash = @{}
    $candidateSamples = [Collections.Generic.List[object]]::new()
    $candidateProbes = [Collections.Generic.List[object]]::new()
    $transitionSourceProbeCount = 0
    $foreignSurfaceProbeCount = 0
    $consecutiveForeignSurfaceProbes = 0
    $foreignSurfaceStartedMilliseconds = 0L
    $foreignSurfaceProbeKey = ""

    while ($LatencyClock.ElapsedMilliseconds -le
        $script:NativeMenuSettleTimeoutMilliseconds) {
        $probe = Get-NativeMenuLayoutProbe `
            -Context $Context `
            -ScreenId $ScreenId
        if ($probe.Status -ne "ready") {
            if ($probe.Status -in @("wrong_surface", "wrong_tab")) {
                $measuredSurface = [string]$probe.SemanticSurface
                if (
                    -not [string]::IsNullOrWhiteSpace(
                        $TransitionalSourceScreen
                    ) -and (Test-NativeMenuScreenTagsEquivalent `
                        -Left $measuredSurface `
                        -Right $TransitionalSourceScreen)
                ) {
                    $transitionSourceProbeCount += 1
                }

                $elapsed = [long]$LatencyClock.ElapsedMilliseconds
                $foreignSurfaceProbeCount += 1
                $probeKey = (
                    [string]$probe.Status + "|" + $measuredSurface + "|" +
                    [string]$probe.NativeSurface + "|" +
                    [string]$probe.NativeGeneration
                )
                if ($probeKey -cne $foreignSurfaceProbeKey) {
                    $foreignSurfaceProbeKey = $probeKey
                    $consecutiveForeignSurfaceProbes = 0
                    $foreignSurfaceStartedMilliseconds = $elapsed
                }
                $consecutiveForeignSurfaceProbes += 1
                if (
                    $consecutiveForeignSurfaceProbes -ge
                        $script:NativeMenuSettleConsecutiveSamples -and
                    ($elapsed - $foreignSurfaceStartedMilliseconds) -ge
                        $script:NativeMenuSettleMinimumSpanMilliseconds
                ) {
                    throw [string]$probe.Detail
                }
                $notReadyCount += 1
                $lastUnavailable = [string]$probe.Detail
                Start-Sleep -Milliseconds (
                    $script:NativeMenuSettlePollMilliseconds
                )
                continue
            }
            $consecutiveForeignSurfaceProbes = 0
            $foreignSurfaceProbeKey = ""
            if ($probe.Status -eq "busy") {
                $busyCount += 1
            } else {
                $notReadyCount += 1
            }
            $lastUnavailable = [string]$probe.Detail
            Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
            continue
        }
        $consecutiveForeignSurfaceProbes = 0
        $foreignSurfaceProbeKey = ""

        $sampleCount += 1
        $elapsed = [long]$LatencyClock.ElapsedMilliseconds
        $structureHash = Get-NativeMenuStringSha256 $probe.NonGeometryJson
        if (-not $structuralPhaseByHash.ContainsKey($structureHash)) {
            $entry = [ordered]@{
                non_geometry_sha256 = $structureHash
                first_seen_milliseconds = $elapsed
                last_seen_milliseconds = $elapsed
                observations = 1
                payload = $probe.SemanticPayload
            }
            $structuralPhaseByHash[$structureHash] = $entry
            $structuralPhaseOrder.Add($structureHash)
        } else {
            $entry = $structuralPhaseByHash[$structureHash]
            $entry["last_seen_milliseconds"] = $elapsed
            $entry["observations"] = [int]$entry["observations"] + 1
        }

        $candidateSamples.Add([ordered]@{
            elapsed_milliseconds = $elapsed
            captured_at_milliseconds = $probe.CapturedAtMilliseconds
            semantic_surface = $probe.SemanticSurface
            semantic_generation = $probe.SemanticGeneration
            native_surface = $probe.NativeSurface
            native_generation = $probe.NativeGeneration
            payload = $probe.SemanticPayload
        })
        $candidateProbes.Add($probe)
        $candidateSpan = if ($candidateSamples.Count -gt 1) {
            $elapsed - [long]$candidateSamples[0].elapsed_milliseconds
        } else {
            0L
        }
        if (
            $candidateSamples.Count -ge $script:NativeMenuSettleConsecutiveSamples -and
            $candidateSpan -ge $script:NativeMenuSettleMinimumSpanMilliseconds
        ) {
            try {
                $classification = Invoke-NativeMenuSettlementClassifier `
                    -Context $Context `
                    -Samples @($candidateSamples)
            } catch {
                $classificationError = [string]$_.Exception.Message
                if ($classificationError -match '^BROKEN:') {
                    throw
                }
                # A rejected candidate is not settlement. Keep measuring until
                # the bounded STOP so transient population, lifecycle churn,
                # and a genuinely invalid surface remain distinguishable.
                $lastRejectedCandidate = $classificationError
                Start-Sleep -Milliseconds (
                    $script:NativeMenuSettlePollMilliseconds
                )
                continue
            }
            $stableStartIndex = [int]$classification.stable_start_index
            $stableEndIndex = [int]$classification.stable_end_index
            if (
                $stableStartIndex -lt 0 -or
                $stableEndIndex -lt $stableStartIndex -or
                $stableEndIndex -ge $candidateSamples.Count
            ) {
                throw (
                    "BROKEN: Settlement v2.9 classifier returned an invalid " +
                    "selected-window index range."
                )
            }
            $stableWindow = [Collections.Generic.List[object]]::new()
            for (
                $stableIndex = $stableStartIndex;
                $stableIndex -le $stableEndIndex;
                $stableIndex += 1
            ) {
                $stableWindow.Add($candidateSamples[$stableIndex])
            }
            if (
                $stableWindow.Count -lt $script:NativeMenuSettleConsecutiveSamples -or
                ([long]$stableWindow[$stableWindow.Count - 1].elapsed_milliseconds -
                    [long]$stableWindow[0].elapsed_milliseconds) -lt
                    $script:NativeMenuSettleMinimumSpanMilliseconds
            ) {
                throw (
                    "BROKEN: Settlement v2.9 classifier selected a window " +
                    "below the recorder's 40-sample/two-second floor."
                )
            }
            $windowAnchorProbe = $candidateProbes[$stableStartIndex]
            $structuralPhases = [Collections.Generic.List[object]]::new()
            foreach ($phaseHash in $structuralPhaseOrder) {
                $structuralPhases.Add($structuralPhaseByHash[$phaseHash])
            }
            foreach ($phase in $structuralPhases) {
                Assert-NativeMenuOverlayHygiene `
                    -Context $Context `
                    -Layout $phase.payload
            }
            $summary = [ordered]@{
                settlement_spec = [string]$classification.settlement_spec
                criterion = [string]$classification.criterion
                structural_element_order = (
                    [string]$classification.structural_element_order
                )
                settle_latency_milliseconds = (
                    [long]$classification.settle_latency_milliseconds
                )
                stable_span_milliseconds = (
                    [long]$classification.stable_span_milliseconds
                )
                consecutive_structural_samples = (
                    [int]$classification.consecutive_structural_samples
                )
                animated_id_set_sample_count = (
                    [int]$classification.animated_id_set_sample_count
                )
                total_semantic_samples = $sampleCount
                busy_probe_count = $busyCount
                not_ready_probe_count = $notReadyCount
                transition_source_probe_count = $transitionSourceProbeCount
                foreign_surface_probe_count = $foreignSurfaceProbeCount
                structural_phase_count = $structuralPhases.Count
                structural_sha256 = [string]$classification.structural_sha256
                animated_element_ids = @(
                    $classification.animated_element_ids
                )
                visibility_cycling_element_ids = @(
                    $classification.visibility_cycling_element_ids
                )
                ephemeral_art_ids = @($classification.ephemeral_art_ids)
                animated_element_count = (
                    [int]$classification.animated_element_count
                )
                minimum_element_count = (
                    [int]$classification.minimum_element_count
                )
                element_count = [int]$classification.element_count
                animated_fraction = [double]$classification.animated_fraction
                stable_start_index = $stableStartIndex
                stable_end_index = $stableEndIndex
            }
            return [pscustomobject]@{
                AnchorProbe = $windowAnchorProbe
                Summary = $summary
                Layout = $classification.layout
                AnimatedElementIds = @($classification.animated_element_ids)
                VisibilityCyclingElementIds = @(
                    $classification.visibility_cycling_element_ids
                )
                EphemeralArtIds = @($classification.ephemeral_art_ids)
                StructuralPhases = $structuralPhases
                SettledWindowSamples = @($stableWindow)
                BrowserTabVerification = (
                    $windowAnchorProbe.BrowserTabVerification
                )
            }
        }
        Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
    }

    throw (
        "STOP: '$ScreenId' never satisfied Settlement v2.9 across at least " +
        "40 samples spanning two seconds within 60 seconds. " +
        "samples=$sampleCount busy=$busyCount not_ready=$notReadyCount " +
        "last_unavailable='$lastUnavailable' " +
        "last_rejected_candidate='$lastRejectedCandidate'"
    )
}

function Test-NativeMenuFrameMatchesSettlement {
    param(
        [Parameter(Mandatory = $true)][object]$FrameProbe,
        [Parameter(Mandatory = $true)][object]$Settlement
    )

    if (
        $FrameProbe.Status -ne "ready" -or
        $FrameProbe.SemanticSurface -cne
            $Settlement.AnchorProbe.SemanticSurface -or
        $FrameProbe.SemanticGeneration -ne
            $Settlement.AnchorProbe.SemanticGeneration -or
        [string]$FrameProbe.SemanticPayload.screen_id -cne
            [string]$Settlement.Layout.screen_id -or
        [uint64]$FrameProbe.SemanticPayload.generation -ne
            [uint64]$Settlement.Layout.generation
    ) {
        return $false
    }
    # Absolute draw ordinals, ambient membership, visibility phases, and
    # animated geometry may all change after the selected window.  The frame
    # is therefore paired to the measured semantic surface and generations;
    # the campaign resolver, not a single post-window frame, contracts the
    # reproduced structural core.
    return $true
}

function Get-SettledNativeMenuObservation {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][string]$FramePath,
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$LatencyClock,
        [string]$TransitionalSourceScreen = ""
    )

    while ($true) {
        $settled = Wait-NativeMenuLayoutSettlement `
            -Context $Context `
            -ScreenId $ScreenId `
            -LatencyClock $LatencyClock `
            -TransitionalSourceScreen $TransitionalSourceScreen
        if (Test-Path -LiteralPath $FramePath -PathType Leaf) {
            Remove-Item -LiteralPath $FramePath -Force
        }
        $frameProbe = Get-NativeMenuLayoutProbe `
            -Context $Context `
            -ScreenId $ScreenId `
            -FramePath $FramePath
        if (-not (Test-NativeMenuFrameMatchesSettlement `
            -FrameProbe $frameProbe `
            -Settlement $settled)) {
            if ($LatencyClock.ElapsedMilliseconds -gt
                $script:NativeMenuSettleTimeoutMilliseconds) {
                throw (
                    "STOP: '$ScreenId' changed while its settled frame was " +
                    "captured and did not re-settle within 60 seconds."
                )
            }
            continue
        }
        if (-not (Test-Path -LiteralPath $FramePath -PathType Leaf)) {
            throw "BROKEN: settled native-menu probe did not create its frame capture."
        }

        $layout = $settled.Layout
        Assert-NativeMenuCaptureSurfaceAgreement `
            -OperatorScreenTag $ScreenId `
            -MachineClassifiedSurface $settled.AnchorProbe.SemanticSurface
        Assert-NativeMenuOverlayHygiene `
            -Context $Context `
            -Layout $layout
        return [pscustomobject]@{
            semantic_surface = $settled.AnchorProbe.SemanticSurface
            machine_classified_surface = (
                $settled.AnchorProbe.MachineClassifiedSurface
            )
            semantic_generation = $settled.AnchorProbe.SemanticGeneration
            native_surface = $settled.AnchorProbe.NativeSurface
            native_generation = $settled.AnchorProbe.NativeGeneration
            tagged_screen = [string]$layout.screen_id
            layout_generation = [uint64]$layout.generation
            element_count = @($layout.elements).Count
            animated_element_ids = @($settled.AnimatedElementIds)
            visibility_cycling_element_ids = @(
                $settled.VisibilityCyclingElementIds
            )
            ephemeral_art_ids = @($settled.EphemeralArtIds)
            capture_method = [string]$layout.capture_method
            frame_sha256 = (
                Get-FileHash -LiteralPath $FramePath -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            settlement = $settled.Summary
            layout = $layout
            browser_tab_verification = $settled.BrowserTabVerification
            settlement_trace = [ordered]@{
                structural_phases = @($settled.StructuralPhases)
                settled_window_samples = @($settled.SettledWindowSamples)
            }
        }
    }
}

function Convert-NativeMenuBmpToPng {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )

    Add-Type -AssemblyName System.Drawing
    $image = [Drawing.Image]::FromFile($SourcePath)
    try {
        $image.Save($DestinationPath, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $image.Dispose()
    }
}
