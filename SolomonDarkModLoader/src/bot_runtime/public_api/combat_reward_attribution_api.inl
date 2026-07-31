namespace {

ParticipantInfo* FindRewardAttributionParticipant(
    RuntimeState& state,
    std::uint64_t participant_id) {
    auto* participant = FindParticipant(state, participant_id);
    const auto local_transport_participant_id =
        GetLocalTransportParticipantId();
    if (participant == nullptr &&
        local_transport_participant_id != 0 &&
        participant_id == local_transport_participant_id) {
        participant = FindLocalParticipant(state);
    }
    return participant;
}

}  // namespace

void ArmSharedKillExperienceCredit(
    const SharedKillExperienceCredit& credit,
    float expected_native_amount) {
    g_pending_shared_kill_experience_credit =
        PendingSharedKillExperienceCredit{};
    if (credit.participant_id == 0 ||
        credit.run_nonce == 0 ||
        !std::isfinite(expected_native_amount) ||
        expected_native_amount <= 0.0f) {
        return;
    }
    g_pending_shared_kill_experience_credit.credit = credit;
    g_pending_shared_kill_experience_credit.expected_native_amount =
        expected_native_amount;
    g_pending_shared_kill_experience_credit.armed_ms =
        static_cast<std::uint64_t>(GetTickCount64());
}

bool ConsumeSharedKillExperienceCredit(
    SharedKillExperienceCredit* credit,
    float* expected_native_amount) {
    if (credit != nullptr) {
        *credit = SharedKillExperienceCredit{};
    }
    if (expected_native_amount != nullptr) {
        *expected_native_amount = 0.0f;
    }
    auto& pending = g_pending_shared_kill_experience_credit;
    const auto now_ms =
        static_cast<std::uint64_t>(GetTickCount64());
    if (pending.armed_ms == 0 ||
        now_ms < pending.armed_ms ||
        now_ms - pending.armed_ms >
            kSharedKillExperienceCreditWindowMs) {
        pending = PendingSharedKillExperienceCredit{};
        return false;
    }
    if (credit != nullptr) {
        *credit = pending.credit;
    }
    if (expected_native_amount != nullptr) {
        *expected_native_amount = pending.expected_native_amount;
    }
    pending = PendingSharedKillExperienceCredit{};
    return true;
}

void ObserveParticipantEnemyDamageRewardAttribution(
    std::uint64_t participant_id,
    double hp_ratio_damage) {
    if (participant_id == 0 ||
        !std::isfinite(hp_ratio_damage) ||
        hp_ratio_damage <= 0.0) {
        return;
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindRewardAttributionParticipant(
            state,
            participant_id);
        if (participant == nullptr ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            participant->runtime.run_nonce == 0) {
            return;
        }
        auto& runtime = participant->runtime;
        if (runtime.reward_attribution_run_nonce !=
            runtime.run_nonce) {
            runtime.reward_attribution_run_nonce =
                runtime.run_nonce;
            runtime.reward_attributed_experience = 0.0;
            runtime.reward_attributed_enemy_hp_ratio_damage = 0.0;
        }
        runtime.reward_attributed_enemy_hp_ratio_damage +=
            hp_ratio_damage;
    });
}

void ObserveParticipantKillExperienceRewardAttribution(
    std::uint64_t participant_id,
    double experience) {
    if (participant_id == 0 ||
        !std::isfinite(experience) ||
        experience <= 0.0) {
        return;
    }
    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = FindRewardAttributionParticipant(
            state,
            participant_id);
        if (participant == nullptr ||
            !participant->runtime.valid ||
            !participant->runtime.in_run ||
            participant->runtime.run_nonce == 0) {
            return;
        }
        auto& runtime = participant->runtime;
        if (runtime.reward_attribution_run_nonce !=
            runtime.run_nonce) {
            runtime.reward_attribution_run_nonce =
                runtime.run_nonce;
            runtime.reward_attributed_experience = 0.0;
            runtime.reward_attributed_enemy_hp_ratio_damage = 0.0;
        }
        runtime.reward_attributed_experience += experience;
    });
}
