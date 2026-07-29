#include "bot_spawn_placement.h"
#include "bot_stuck_progress.h"
#include "multiplayer_local_udp_framing.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"
#include "participant_hit_feedback_flow_control.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

namespace {

bool Require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

bool NearlyEqual(float left, float right, float epsilon = 0.001f) {
    return std::fabs(left - right) <= epsilon;
}

sdmod::multiplayer::WorldSnapshotRuntimeInfo MakeWorldSnapshot(
    std::uint32_t sequence,
    std::uint64_t received_ms,
    float position_x) {
    using namespace sdmod::multiplayer;

    WorldActorSnapshot actor;
    actor.network_actor_id = 0x1001;
    actor.native_type_id = 1001;
    actor.position_x = position_x;
    actor.position_y = 20.0f;
    actor.heading = 350.0f;

    WorldSnapshotRuntimeInfo snapshot;
    snapshot.valid = true;
    snapshot.authority_participant_id = 42;
    snapshot.received_ms = received_ms;
    snapshot.sequence = sequence;
    snapshot.scene_epoch = 7;
    snapshot.run_nonce = 11;
    snapshot.actor_total_count = 1;
    snapshot.scene_intent.kind = ParticipantSceneIntentKind::Run;
    snapshot.actors.push_back(actor);
    return snapshot;
}

bool FixedWorldDelayDoesNotAmplifyArrivalJitter() {
    using namespace sdmod::multiplayer;

    RuntimeState state;
    AppendWorldSnapshot(&state, MakeWorldSnapshot(1, 1000, 0.0f));
    AppendWorldSnapshot(&state, MakeWorldSnapshot(2, 1200, 20.0f));

    WorldSnapshotRuntimeInfo sample;
    if (!Require(
            TrySampleWorldSnapshot(state, 1250, 150, &sample),
            "fixed-delay world sample was unavailable") ||
        !Require(
            sample.actors.size() == 1,
            "fixed-delay world sample lost its actor") ||
        !Require(
            NearlyEqual(sample.actors[0].position_x, 10.0f),
            "fixed-delay world sample did not interpolate at 150 ms")) {
        return false;
    }

    AppendWorldSnapshot(&state, MakeWorldSnapshot(3, 1300, 30.0f));
    return Require(
        TrySampleWorldSnapshot(state, 1350, 150, &sample) &&
            sample.actors.size() == 1 &&
            NearlyEqual(sample.actors[0].position_x, 20.0f),
        "arrival jitter changed the fixed 150 ms presentation delay");
}

bool RemotePlayerExtrapolatesAtMostOneArrival() {
    using namespace sdmod::multiplayer;

    ParticipantInfo participant;
    participant.runtime.movement_intent_x = 1.0f;
    participant.runtime.movement_intent_y = 0.0f;

    ParticipantTransformSample first;
    first.valid = true;
    first.received_ms = 1000;
    first.sequence = 1;
    first.run_nonce = 11;
    first.scene_intent.kind = ParticipantSceneIntentKind::Run;
    first.position_x = 0.0f;

    auto second = first;
    second.received_ms = 1050;
    second.sequence = 2;
    second.position_x = 5.0f;
    AppendParticipantTransformSample(&participant, first);
    AppendParticipantTransformSample(&participant, second);

    ParticipantTransformSample sample;
    if (!Require(
            TrySampleParticipantTransform(participant, 1190, 120, &sample),
            "remote extrapolation sample was unavailable") ||
        !Require(
            NearlyEqual(sample.position_x, 7.0f),
            "remote extrapolation did not project the observed velocity")) {
        return false;
    }

    if (!Require(
            TrySampleParticipantTransform(participant, 1300, 120, &sample),
            "bounded remote extrapolation sample was unavailable") ||
        !Require(
            NearlyEqual(sample.position_x, 10.0f),
            "remote extrapolation exceeded or missed the one-arrival cap")) {
        return false;
    }

    participant.runtime.movement_intent_x = 0.0f;
    return Require(
               TrySampleParticipantTransform(participant, 1190, 120, &sample),
               "remote hold sample was unavailable") &&
           Require(
               NearlyEqual(sample.position_x, 5.0f),
               "remote extrapolation ignored the stopped movement intent");
}

bool ParticipantCapacityCountsHumansAndBotsTogether() {
    using namespace sdmod::multiplayer;

    RuntimeState state;
    if (!Require(
            kNativeParticipantCapacity == 4 &&
                kDefaultParticipantCapacity == 4 &&
                kMinimumParticipantCapacity == 2,
            "participant capacity constants do not match the native four-slot ceiling") ||
        !Require(
            IsSupportedParticipantCapacity(2) &&
                IsSupportedParticipantCapacity(4) &&
                !IsSupportedParticipantCapacity(1) &&
                !IsSupportedParticipantCapacity(5),
            "participant capacity validation crossed the native ceiling") ||
        !Require(
            ResolveParticipantCapacity(state) == 4,
            "default participant capacity is not four")) {
        return false;
    }

    ParticipantInfo local;
    local.participant_id = kLocalParticipantId;
    local.kind = ParticipantKind::LocalHuman;
    local.controller_kind = ParticipantControllerKind::Native;
    local.transport_connected = true;
    state.participants.push_back(local);

    ParticipantInfo remote_human;
    remote_human.participant_id = 2;
    remote_human.kind = ParticipantKind::RemoteParticipant;
    remote_human.controller_kind = ParticipantControllerKind::Native;
    remote_human.transport_connected = true;
    state.participants.push_back(remote_human);

    ParticipantInfo first_bot;
    first_bot.participant_id = kFirstLuaControlledParticipantId;
    first_bot.kind = ParticipantKind::RemoteParticipant;
    first_bot.controller_kind = ParticipantControllerKind::LuaBrain;
    first_bot.transport_connected = true;
    state.participants.push_back(first_bot);

    auto second_bot = first_bot;
    second_bot.participant_id += 1;
    state.participants.push_back(second_bot);

    if (!Require(
            CountHumanParticipantSeats(state) == 2,
            "connected local and remote humans did not consume two seats") ||
        !Require(
            CountBotParticipantSeats(state) == 2,
            "Lua-controlled participants did not consume two seats") ||
        !Require(
            CountOccupiedParticipantSeats(state) == 4,
            "humans and bots were not counted against one capacity") ||
        !Require(
            !HasOpenParticipantSeat(state) &&
                !CanAdmitHumanParticipant(state, 3),
            "a full bot-backed lobby admitted another participant")) {
        return false;
    }

    state.participants.pop_back();
    if (!Require(
            HasOpenParticipantSeat(state) &&
                CanAdmitHumanParticipant(state, 3),
            "despawning a bot did not free a human participant seat")) {
        return false;
    }
    state.participants.push_back(second_bot);

    state.session_human_participant_count = 3;
    if (!Require(
            CountHumanParticipantSeats(state) == 3 &&
                CountOccupiedParticipantSeats(state) == 5,
            "lobby membership did not reserve seats for humans before runtime materialization")) {
        return false;
    }

    state.session_max_participants = 2;
    return Require(
        ResolveParticipantCapacity(state) == 2,
        "supported configured capacity was ignored");
}

bool BotSpawnPlacementKeepsClearAnchor() {
    using namespace sdmod;

    BotSpawnPlacementResult result;
    std::uint32_t probes = 0;
    const auto clear = [&](float x, float y) {
        ++probes;
        return NearlyEqual(x, 12.0f) && NearlyEqual(y, -8.0f)
            ? BotSpawnPlacementProbeResult::Clear
            : BotSpawnPlacementProbeResult::Blocked;
    };
    return Require(
               FindNearestClearBotSpawnPlacement(
                   12.0f,
                   -8.0f,
                   25.0f,
                   clear,
                   &result),
               "clear bot spawn anchor was rejected") &&
        Require(
            NearlyEqual(result.x, 12.0f) &&
                NearlyEqual(result.y, -8.0f) &&
                NearlyEqual(result.search_distance, 0.0f),
            "clear bot spawn anchor moved") &&
        Require(
            probes == 1 && result.probe_count == 1,
            "clear bot spawn anchor used more than one native probe");
}

bool BotSpawnPlacementSearchesPastBlockedNaiveAnchor() {
    using namespace sdmod;

    BotSpawnPlacementResult result;
    const auto clear = [](float x, float y) {
        const auto distance = std::sqrt(x * x + y * y);
        return distance >= 49.0f && x > 0.0f
            ? BotSpawnPlacementProbeResult::Clear
            : BotSpawnPlacementProbeResult::Blocked;
    };
    if (!Require(
            FindNearestClearBotSpawnPlacement(
                0.0f,
                0.0f,
                25.0f,
                clear,
                &result),
            "blocked naive anchor did not find a clear ring position")) {
        return false;
    }

    return Require(
               !NearlyEqual(result.x, 0.0f) ||
                   !NearlyEqual(result.y, 0.0f),
               "blocked naive anchor was returned unchanged") &&
        Require(
            NearlyEqual(result.search_distance, 50.0f),
            "blocked anchor search did not choose the nearest clear ring") &&
        Require(
            result.probe_count > 1 &&
                result.probe_count <= kBotSpawnPlacementMaximumProbeCount,
            "blocked anchor search escaped its deterministic probe bound");
}

bool BotSpawnPlacementExhaustionIsBounded() {
    using namespace sdmod;

    BotSpawnPlacementResult result;
    std::uint32_t probes = 0;
    const auto blocked = [&](float, float) {
        ++probes;
        return BotSpawnPlacementProbeResult::Blocked;
    };
    return Require(
               !FindNearestClearBotSpawnPlacement(
                   100.0f,
                   200.0f,
                   25.0f,
                   blocked,
                   &result),
               "fully blocked bot spawn unexpectedly succeeded") &&
        Require(
            probes == result.probe_count &&
                probes > 1 &&
                probes <= kBotSpawnPlacementMaximumProbeCount,
            "fully blocked bot spawn search was not bounded") &&
        Require(
            NearlyEqual(
                result.search_distance,
                BotSpawnPlacementSearchBound(25.0f)),
            "fully blocked bot spawn did not report its search bound");
}

bool BotSpawnPlacementStopsWhenNativeProbeIsUnavailable() {
    using namespace sdmod;

    BotSpawnPlacementResult result;
    std::uint32_t probes = 0;
    const auto unavailable = [&](float, float) {
        ++probes;
        return BotSpawnPlacementProbeResult::Unavailable;
    };
    return Require(
               !FindNearestClearBotSpawnPlacement(
                   0.0f,
                   0.0f,
                   25.0f,
                   unavailable,
                   &result),
               "unavailable native placement probe unexpectedly succeeded") &&
        Require(
            result.probe_unavailable &&
                result.probe_count == 1 &&
                probes == 1,
            "unavailable native placement probe did not stop immediately");
}

bool BotStuckProgressRequiresAFullRollingWindow() {
    using namespace sdmod;

    BotStuckProgressTracker tracker;
    return Require(
               !ObserveBotStuckProgress(
                   &tracker, 1000, 500.0f, 600.0f, 200.0f, false),
               "stuck tracking fired on its first sample") &&
        Require(
            !ObserveBotStuckProgress(
                &tracker, 30999, 500.0f, 600.0f, 200.0f, false),
            "stuck tracking fired before 30 seconds") &&
        Require(
            ObserveBotStuckProgress(
                &tracker, 31000, 500.0f, 600.0f, 200.0f, false),
            "stuck tracking did not fire at 30 seconds");
}

bool BotStuckProgressAcceptsSlowReachableMovement() {
    using namespace sdmod;

    BotStuckProgressTracker tracker;
    for (std::uint64_t now_ms = 1000; now_ms <= 41000; now_ms += 1000) {
        const auto elapsed_seconds =
            static_cast<float>((now_ms - 1000) / 1000);
        const auto distance = 200.0f - elapsed_seconds * 0.25f;
        if (!Require(
                !ObserveBotStuckProgress(
                    &tracker,
                    now_ms,
                    500.0f,
                    600.0f,
                    distance,
                    false),
                "slow reachable movement triggered a stuck teleport")) {
            return false;
        }
    }
    return true;
}

bool BotStuckProgressSeparatesWaypointsFromSegmentExhaustion() {
    using namespace sdmod;

    BotStuckProgressTracker waypoint_tracker;
    if (!Require(
            !ObserveBotStuckProgress(
                &waypoint_tracker,
                1000,
                500.0f,
                600.0f,
                200.0f,
                false),
            "waypoint tracker fired on its first sample") ||
        !Require(
            !ObserveBotStuckProgress(
                &waypoint_tracker,
                20000,
                500.0f,
                600.0f,
                200.0f,
                true),
            "meaningful waypoint progress fired a teleport") ||
        !Require(
            !ObserveBotStuckProgress(
                &waypoint_tracker,
                31000,
                500.0f,
                600.0f,
                200.0f,
                false),
            "waypoint progress inside the rolling window was ignored")) {
        return false;
    }
    DiscardBotStuckWaypointProgress(&waypoint_tracker);
    if (!Require(
            ObserveBotStuckProgress(
                &waypoint_tracker,
                31001,
                500.0f,
                600.0f,
                200.0f,
                false),
            "exhausted segment retained stale waypoint credit")) {
        return false;
    }

    BotStuckProgressTracker exhausted_tracker;
    return Require(
               !ObserveBotStuckProgress(
                   &exhausted_tracker,
                   1000,
                   500.0f,
                   600.0f,
                   200.0f,
                   false),
               "exhaustion tracker fired on its first sample") &&
        Require(
            ObserveBotStuckProgress(
                &exhausted_tracker,
                31000,
                500.0f,
                600.0f,
                200.0f,
                false),
            "segment exhaustion without progress prevented recovery");
}

bool BotStuckProgressRejectsRepeatedDistanceOscillation() {
    using namespace sdmod;

    BotStuckProgressTracker tracker;
    return Require(
               !ObserveBotStuckProgress(
                   &tracker,
                   1000,
                   500.0f,
                   600.0f,
                   200.0f,
                   false),
               "oscillation tracker fired on its first sample") &&
        Require(
            !ObserveBotStuckProgress(
                &tracker,
                8000,
                500.0f,
                600.0f,
                198.0f,
                false),
            "opening oscillation fired before a full window") &&
        Require(
            !ObserveBotStuckProgress(
                &tracker,
                16000,
                500.0f,
                600.0f,
                200.0f,
                false),
            "mid-window oscillation fired before a full window") &&
        Require(
            !ObserveBotStuckProgress(
                &tracker,
                24000,
                500.0f,
                600.0f,
                198.0f,
                false),
            "closing oscillation fired before a full window") &&
        Require(
            ObserveBotStuckProgress(
                &tracker,
                31000,
                500.0f,
                600.0f,
                200.0f,
                false),
            "repeated far-to-near oscillation counted as new progress");
}

bool BotStuckProgressResetsForNewTargetsAndHonorsCooldown() {
    using namespace sdmod;

    BotStuckProgressTracker tracker;
    (void)ObserveBotStuckProgress(
        &tracker, 1000, 500.0f, 600.0f, 200.0f, false);
    if (!Require(
            !ObserveBotStuckProgress(
                &tracker, 31000, 700.0f, 800.0f, 200.0f, false),
            "materially different target inherited the old stuck window") ||
        !Require(
            ObserveBotStuckProgress(
                &tracker, 61000, 700.0f, 800.0f, 200.0f, false),
            "new continuous target did not mature its own stuck window")) {
        return false;
    }

    RecordBotStuckTeleport(&tracker, 61000);
    return Require(
               !ObserveBotStuckProgress(
                   &tracker, 91000, 700.0f, 800.0f, 200.0f, false),
               "teleport cooldown retained the pre-teleport window") &&
        Require(
            !ObserveBotStuckProgress(
                &tracker, 101000, 700.0f, 800.0f, 200.0f, false),
            "teleport cooldown allowed an immediate loop");
}

bool PacketSplitsHaveBoundedVariableWireSizes() {
    using namespace sdmod::multiplayer;

    return Require(
               kProtocolVersion == 88,
               "native and launcher protocol version changed unexpectedly") &&
        Require(
            std::string(
                LobbySessionStateLabel(
                    LobbySessionState::NotInGame)) ==
                "not-in-game" &&
                std::string(
                    LobbySessionStateLabel(
                        LobbySessionState::InHub)) ==
                    "in-hub" &&
                std::string(
                    LobbySessionStateLabel(
                        LobbySessionState::InBoneyard)) ==
                    "in-boneyard",
            "lobby session-state JSON labels changed") &&
        Require(
            std::string(
                RunLoadingReleaseReasonLabel(
                    RunLoadingReleaseReason::
                        AllParticipantsReady)) ==
                "all-participants-ready" &&
                std::string(
                    RunLoadingReleaseReasonLabel(
                        RunLoadingReleaseReason::Timeout)) ==
                    "timeout",
            "run-loading release labels changed") &&
        Require(
            ResolveParticipantDeathPresentationTick(0) == 0 &&
                ResolveParticipantDeathPresentationTick(2500) == 150 &&
                ResolveParticipantDeathPresentationTick(2517) == 151 &&
                ResolveParticipantDeathPresentationTick(5000) == 298 &&
                ResolveParticipantDeathPresentationTick(10000) == 298,
            "death presentation wire clock is not bounded to the native lifecycle") &&
        Require(
            ResolveParticipantDeathPresentationStorageTick(149) == 149 &&
                ResolveParticipantDeathPresentationStorageTick(150) == 150 &&
                ResolveParticipantDeathPresentationStorageTick(151) == 150 &&
                ResolveParticipantDeathPresentationStorageTick(298) == 150,
            "death presentation CPU timer can cross the native side-effect boundary") &&
        Require(
            ResolveParticipantDeathPresentationRenderTick(149) == 149 &&
                ResolveParticipantDeathPresentationRenderTick(150) == 150 &&
                ResolveParticipantDeathPresentationRenderTick(151) == 151 &&
                ResolveParticipantDeathPresentationRenderTick(159) == 159 &&
                ResolveParticipantDeathPresentationRenderTick(298) == 159,
            "death presentation render projection does not reach and hold the corpse frame") &&
        Require(
            sizeof(StatePacket) == 657,
            "StatePacket regained checkpoint-array payload") &&
        Require(
            sizeof(ParticipantFramePacket) == 374,
            "ParticipantFramePacket regained wave-summary payload") &&
        Require(
            ParticipantInventorySnapshotPacketWireSize(0) ==
                kParticipantInventorySnapshotPacketPrefixBytes,
            "empty inventory snapshot wire size is invalid") &&
        Require(
            ParticipantProgressionBookSnapshotPacketWireSize(0) ==
                kParticipantProgressionBookSnapshotPacketPrefixBytes,
            "empty progression snapshot wire size is invalid") &&
        Require(
            LevelUpBarrierPacketWireSize(1) ==
                kLevelUpBarrierPacketPrefixBytes +
                    sizeof(LevelUpBarrierParticipantPacketState),
            "single-participant level-up barrier wire size is invalid") &&
        Require(
            IsValidLevelUpBarrierPacketWireSize(
                sizeof(LevelUpBarrierPacket),
                static_cast<std::uint8_t>(
                    kLevelUpWaitStatusMaxParticipants)),
            "250-participant level-up barrier does not consume its full packet") &&
        Require(
            !IsValidLevelUpBarrierPacketWireSize(
                sizeof(LevelUpBarrierPacket) - 1,
                static_cast<std::uint8_t>(
                    kLevelUpWaitStatusMaxParticipants)),
            "truncated level-up barrier wire size was accepted");
}

bool LocalUdpFramingStaysBelowPathMtuAndReassembles() {
    using namespace sdmod::multiplayer;

    ParticipantProgressionBookSnapshotPacket packet{};
    packet.header = MakePacketHeader(
        PacketKind::ParticipantProgressionBookSnapshot,
        42);
    packet.entry_count = 83;
    const auto packet_bytes =
        ParticipantProgressionBookSnapshotPacketWireSize(
            packet.entry_count);
    if (!Require(
            packet_bytes == 1704,
            "WAN regression fixture is not the captured 1704-byte packet")) {
        return false;
    }

    std::vector<std::vector<std::uint8_t>> datagrams;
    if (!Require(
            BuildLocalUdpFragmentDatagrams(
                &packet,
                packet_bytes,
                &datagrams),
            "oversized local UDP packet was not fragmented") ||
        !Require(
            datagrams.size() == 2,
            "captured progression packet did not produce two datagrams") ||
        !Require(
            datagrams[0].size() ==
                    kLocalUdpMaximumDatagramBytes &&
                datagrams[1].size() <
                    kLocalUdpMaximumDatagramBytes,
            "transport fragment crossed the 1200-byte wire ceiling")) {
        return false;
    }

    LocalUdpFragmentReassembler reassembler;
    std::vector<std::uint8_t> completed;
    if (!Require(
            reassembler.Accept(
                7,
                datagrams[1].data(),
                datagrams[1].size(),
                1000,
                &completed) ==
                LocalUdpFragmentAcceptResult::Pending,
            "out-of-order final fragment was rejected") ||
        !Require(
            reassembler.Accept(
                7,
                datagrams[1].data(),
                datagrams[1].size(),
                1001,
                &completed) ==
                LocalUdpFragmentAcceptResult::Pending,
            "duplicate fragment corrupted its assembly") ||
        !Require(
            reassembler.Accept(
                7,
                datagrams[0].data(),
                datagrams[0].size(),
                1002,
                &completed) ==
                LocalUdpFragmentAcceptResult::Complete,
            "out-of-order fragment assembly did not complete") ||
        !Require(
            completed.size() == packet_bytes &&
                std::memcmp(
                    completed.data(),
                    &packet,
                    packet_bytes) == 0,
            "reassembled local UDP packet differs from its input")) {
        return false;
    }

    if (!Require(
            reassembler.Accept(
                7,
                datagrams[0].data(),
                datagrams[0].size(),
                2000,
                &completed) ==
                LocalUdpFragmentAcceptResult::Pending,
            "fresh incomplete fragment did not create an assembly")) {
        return false;
    }
    reassembler.Prune(
        2000 +
        kLocalUdpFragmentAssemblyExpiryMicroseconds);
    return Require(
               reassembler.pending_assembly_count() == 0 &&
                   reassembler.pending_bytes() == 0,
               "expired fragment assembly retained bounded state") &&
        Require(
            !BuildLocalUdpFragmentDatagrams(
                &packet,
                kLocalUdpMaximumLogicalPacketBytes + 1,
                &datagrams),
            "transport accepted a logical packet above its hard bound");
}

bool HitFeedbackRecoveryUsesABoundedCumulativeAckWindow() {
    using namespace sdmod::multiplayer;

    std::vector<std::uint64_t> last_sent_ms(20, 0);
    std::size_t in_flight_count = 0;
    std::size_t sends_this_tick = 0;
    std::vector<std::size_t> selected;
    for (std::size_t index = 0;
         index < last_sent_ms.size();
         ++index) {
        const auto action =
            SelectParticipantHitFeedbackSendAction(
                index,
                last_sent_ms[index],
                1000,
                in_flight_count,
                sends_this_tick);
        if (action == ParticipantHitFeedbackSendAction::None) {
            continue;
        }
        selected.push_back(index);
        last_sent_ms[index] = 1000;
        ++in_flight_count;
        ++sends_this_tick;
    }
    if (!Require(
            selected == std::vector<std::size_t>({0, 1, 2, 3}),
            "hit-feedback first-send burst exceeded its per-tick budget")) {
        return false;
    }

    sends_this_tick = 0;
    selected.clear();
    for (std::size_t index = 0;
         index < last_sent_ms.size();
         ++index) {
        const auto action =
            SelectParticipantHitFeedbackSendAction(
                index,
                last_sent_ms[index],
                1050,
                in_flight_count,
                sends_this_tick);
        if (action == ParticipantHitFeedbackSendAction::FirstSend) {
            selected.push_back(index);
            last_sent_ms[index] = 1050;
            ++in_flight_count;
            ++sends_this_tick;
        }
    }
    if (!Require(
            selected == std::vector<std::size_t>({4, 5, 6, 7}),
            "hit-feedback send window did not fill predictably")) {
        return false;
    }

    sends_this_tick = 0;
    selected.clear();
    for (std::size_t index = 0;
         index < last_sent_ms.size();
         ++index) {
        const auto action =
            SelectParticipantHitFeedbackSendAction(
                index,
                last_sent_ms[index],
                1101,
                in_flight_count,
                sends_this_tick);
        if (action != ParticipantHitFeedbackSendAction::None) {
            selected.push_back(index);
            ++sends_this_tick;
        }
    }
    return Require(
               selected == std::vector<std::size_t>({0}),
               "cumulative-ACK recovery resent more than the oldest gap") &&
        Require(
            SelectParticipantHitFeedbackSendAction(
                8,
                0,
                1101,
                in_flight_count,
                0) ==
                ParticipantHitFeedbackSendAction::None,
            "hit-feedback flow control admitted work beyond its window");
}

}  // namespace

int main() {
    if (!FixedWorldDelayDoesNotAmplifyArrivalJitter() ||
        !RemotePlayerExtrapolatesAtMostOneArrival() ||
        !ParticipantCapacityCountsHumansAndBotsTogether() ||
        !BotSpawnPlacementKeepsClearAnchor() ||
        !BotSpawnPlacementSearchesPastBlockedNaiveAnchor() ||
        !BotSpawnPlacementExhaustionIsBounded() ||
        !BotSpawnPlacementStopsWhenNativeProbeIsUnavailable() ||
        !BotStuckProgressRequiresAFullRollingWindow() ||
        !BotStuckProgressAcceptsSlowReachableMovement() ||
        !BotStuckProgressSeparatesWaypointsFromSegmentExhaustion() ||
        !BotStuckProgressRejectsRepeatedDistanceOscillation() ||
        !BotStuckProgressResetsForNewTargetsAndHonorsCooldown() ||
        !PacketSplitsHaveBoundedVariableWireSizes() ||
        !LocalUdpFramingStaysBelowPathMtuAndReassembles() ||
        !HitFeedbackRecoveryUsesABoundedCumulativeAckWindow()) {
        return 1;
    }

    std::cout << "Multiplayer runtime state tests passed\n";
    return 0;
}
