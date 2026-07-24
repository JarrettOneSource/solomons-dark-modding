// Change-gated reliable inventory and progression-book snapshots.

bool BuildLocalParticipantInventorySnapshotPacket(
    ParticipantInventorySnapshotPacket* packet) {
    if (packet == nullptr) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr) {
        return false;
    }

    ParticipantInventorySnapshotPacket built{};
    built.header = MakePacketHeader(
        PacketKind::ParticipantInventorySnapshot,
        g_local_transport.next_sequence++);
    built.participant_id = g_local_transport.local_peer_id;
    built.participant_session_nonce =
        g_local_transport.local_session_nonce;
    built.inventory_revision =
        local->owned_progression.inventory_revision;
    const auto item_count = (std::min)(
        local->owned_progression.inventory_items.size(),
        static_cast<std::size_t>(
            kParticipantInventorySnapshotMaxItems));
    built.item_count =
        static_cast<std::uint16_t>(item_count);
    built.item_total_count =
        local->owned_progression.inventory_item_total_count;
    built.snapshot_flags =
        local->owned_progression.inventory_truncated ||
            local->owned_progression.inventory_items.size() >
                kParticipantInventorySnapshotMaxItems
            ? ParticipantInventorySnapshotFlagTruncated
            : 0;
    for (std::size_t index = 0;
         index < item_count;
         ++index) {
        const auto& item =
            local->owned_progression.inventory_items[index];
        auto& packet_item = built.items[index];
        packet_item.type_id = item.type_id;
        packet_item.recipe_uid = item.recipe_uid;
        packet_item.content_id = item.content_id;
        packet_item.slot = item.slot;
        packet_item.stack_count = item.stack_count;
        packet_item.parent_item_index =
            item.parent_item_index;
        packet_item.container_depth = item.container_depth;
    }
    *packet = built;
    return true;
}

bool BuildLocalParticipantProgressionBookSnapshotPacket(
    ParticipantProgressionBookSnapshotPacket* packet) {
    if (packet == nullptr) {
        return false;
    }

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr) {
        return false;
    }

    ParticipantProgressionBookSnapshotPacket built{};
    built.header = MakePacketHeader(
        PacketKind::ParticipantProgressionBookSnapshot,
        g_local_transport.next_sequence++);
    built.participant_id = g_local_transport.local_peer_id;
    built.participant_session_nonce =
        g_local_transport.local_session_nonce;
    built.spellbook_revision =
        local->owned_progression.spellbook_revision;
    built.statbook_revision =
        local->owned_progression.statbook_revision;
    const auto entry_count = (std::min)(
        local->owned_progression
            .progression_book_entries.size(),
        static_cast<std::size_t>(
            kParticipantProgressionBookSnapshotMaxEntries));
    built.entry_count =
        static_cast<std::uint16_t>(entry_count);
    built.entry_total_count =
        local->owned_progression
            .progression_book_entry_total_count;
    built.snapshot_flags =
        local->owned_progression
                .progression_book_truncated ||
            local->owned_progression
                    .progression_book_entries.size() >
                kParticipantProgressionBookSnapshotMaxEntries
            ? ParticipantProgressionBookSnapshotFlagTruncated
            : 0;
    for (std::size_t index = 0;
         index < entry_count;
         ++index) {
        const auto& entry =
            local->owned_progression
                .progression_book_entries[index];
        auto& packet_entry = built.entries[index];
        packet_entry.entry_index = entry.entry_index;
        packet_entry.internal_id = entry.internal_id;
        packet_entry.active = entry.active;
        packet_entry.visible = entry.visible;
        packet_entry.category = entry.category;
        packet_entry.statbook_max_level =
            entry.statbook_max_level;
    }
    *packet = built;
    return true;
}

bool SteamParticipantInventorySnapshotOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id) {
    if (data == nullptr ||
        size <
            kParticipantInventorySnapshotPacketPrefixBytes ||
        size > sizeof(ParticipantInventorySnapshotPacket)) {
        return false;
    }
    ParticipantInventorySnapshotPacket packet{};
    std::memcpy(&packet, data, size);
    return IsValidHeader(
               packet.header,
               PacketKind::ParticipantInventorySnapshot) &&
        IsValidParticipantInventorySnapshotPacketWireSize(
            size,
            packet.item_count) &&
        packet.participant_id == sender_steam_id;
}

bool SteamParticipantProgressionBookSnapshotOwnerMatches(
    const void* data,
    std::size_t size,
    std::uint64_t sender_steam_id) {
    if (data == nullptr ||
        size <
            kParticipantProgressionBookSnapshotPacketPrefixBytes ||
        size >
            sizeof(
                ParticipantProgressionBookSnapshotPacket)) {
        return false;
    }
    ParticipantProgressionBookSnapshotPacket packet{};
    std::memcpy(&packet, data, size);
    return IsValidHeader(
               packet.header,
               PacketKind::
                   ParticipantProgressionBookSnapshot) &&
        IsValidParticipantProgressionBookSnapshotPacketWireSize(
            size,
            packet.entry_count) &&
        packet.participant_id == sender_steam_id;
}

bool ParticipantProgressionSnapshotSessionMatches(
    std::uint64_t participant_id,
    std::uint64_t participant_session_nonce) {
    if (participant_id == 0 ||
        participant_session_nonce == 0 ||
        participant_id == kLocalParticipantId ||
        participant_id == g_local_transport.local_peer_id) {
        return false;
    }
    const auto session =
        g_local_transport.session_nonce_by_participant.find(
            participant_id);
    return session !=
            g_local_transport
                .session_nonce_by_participant.end() &&
        session->second == participant_session_nonce;
}

bool ParticipantProgressionSnapshotSourceMatches(
    std::uint64_t participant_id,
    const TransportPeerEndpoint& from) {
    if (IsLocalTransportClient()) {
        return IsConfiguredRemoteAuthorityEndpoint(from);
    }
    if (!IsLocalTransportHost()) {
        return false;
    }
    return std::any_of(
        g_local_transport.peers.begin(),
        g_local_transport.peers.end(),
        [&](const LocalPeerEndpoint& peer) {
            return peer.participant_id == participant_id &&
                SameEndpoint(peer.endpoint, from);
        });
}

bool IsSaneParticipantInventorySnapshot(
    const ParticipantInventorySnapshotPacket& packet) {
    if (packet.item_count >
            kParticipantInventorySnapshotMaxItems ||
        packet.item_total_count < packet.item_count) {
        return false;
    }

    for (std::size_t index = 0;
         index < packet.item_count;
         ++index) {
        const auto& item = packet.items[index];
        std::int32_t local_slot = item.slot;
        if (item.type_id == 0 ||
            (item.type_id == kPotionItemTypeId &&
             !TryResolvePotionWireIdentity(
                 item.slot,
                 item.content_id,
                 &local_slot)) ||
            (item.type_id != kPotionItemTypeId &&
             item.content_id != 0) ||
            item.container_depth >
                kSDModInventorySnapshotMaxDepth) {
            return false;
        }
        if (item.container_depth == 0) {
            if (item.parent_item_index != -1) {
                return false;
            }
            continue;
        }
        if (item.parent_item_index < 0 ||
            static_cast<std::size_t>(
                item.parent_item_index) >= index) {
            return false;
        }
        const auto& parent =
            packet.items[item.parent_item_index];
        if (parent.type_id != 0x1B60 ||
            item.container_depth !=
                static_cast<std::uint16_t>(
                    parent.container_depth + 1)) {
            return false;
        }
    }
    return true;
}

bool IsSaneParticipantProgressionBookSnapshot(
    const ParticipantProgressionBookSnapshotPacket& packet) {
    if (packet.entry_count >
            kParticipantProgressionBookSnapshotMaxEntries ||
        packet.entry_total_count < packet.entry_count) {
        return false;
    }
    std::unordered_set<std::int32_t> entry_indices;
    entry_indices.reserve(packet.entry_count);
    for (std::size_t index = 0;
         index < packet.entry_count;
         ++index) {
        const auto& entry = packet.entries[index];
        if (entry.entry_index < 0 ||
            entry.entry_index >= static_cast<std::int32_t>(
                kParticipantProgressionBookSnapshotMaxEntries) ||
            !entry_indices.insert(entry.entry_index).second) {
            return false;
        }
    }
    return true;
}

void ApplyParticipantInventorySnapshotPacket(
    const ParticipantInventorySnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!ParticipantProgressionSnapshotSourceMatches(
            packet.participant_id,
            from) ||
        !ParticipantProgressionSnapshotSessionMatches(
            packet.participant_id,
            packet.participant_session_nonce) ||
        !IsSaneParticipantInventorySnapshot(packet)) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayPacketBufferToPeers(
        &packet,
        ParticipantInventorySnapshotPacketWireSize(
            packet.item_count),
        from,
        SteamNetworkSendMode::ReliableNoNagle);

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = UpsertRemoteParticipant(
            state,
            packet.participant_id,
            ParticipantControllerKind::Native);
        if (participant == nullptr ||
            packet.inventory_revision <
                participant->owned_progression
                    .inventory_revision) {
            return;
        }

        auto& progression =
            participant->owned_progression;
        progression.initialized = true;
        progression.inventory_revision =
            packet.inventory_revision;
        progression.inventory_item_total_count =
            packet.item_total_count;
        progression.inventory_truncated =
            (packet.snapshot_flags &
             ParticipantInventorySnapshotFlagTruncated) != 0;
        progression.inventory_items.clear();
        progression.inventory_items.reserve(
            packet.item_count);
        for (std::size_t index = 0;
             index < packet.item_count;
             ++index) {
            const auto& packet_item = packet.items[index];
            ParticipantInventoryItemState item;
            item.type_id = packet_item.type_id;
            item.recipe_uid = packet_item.recipe_uid;
            item.content_id = packet_item.content_id;
            item.slot = packet_item.slot;
            if (item.type_id == kPotionItemTypeId) {
                std::int32_t local_slot = -1;
                if (!TryResolvePotionWireIdentity(
                        packet_item.slot,
                        packet_item.content_id,
                        &local_slot)) {
                    continue;
                }
                item.slot = local_slot;
            }
            item.stack_count = packet_item.stack_count;
            item.parent_item_index =
                packet_item.parent_item_index;
            item.container_depth =
                packet_item.container_depth;
            progression.inventory_items.push_back(item);
        }
    });
}

void ApplyParticipantProgressionBookSnapshotPacket(
    const ParticipantProgressionBookSnapshotPacket& packet,
    const TransportPeerEndpoint& from,
    std::uint64_t now_ms) {
    if (!ParticipantProgressionSnapshotSourceMatches(
            packet.participant_id,
            from) ||
        !ParticipantProgressionSnapshotSessionMatches(
            packet.participant_id,
            packet.participant_session_nonce) ||
        !IsSaneParticipantProgressionBookSnapshot(packet)) {
        return;
    }

    UpsertPeerEndpoint(from, packet.participant_id, now_ms);
    RelayPacketBufferToPeers(
        &packet,
        ParticipantProgressionBookSnapshotPacketWireSize(
            packet.entry_count),
        from,
        SteamNetworkSendMode::ReliableNoNagle);

    UpdateRuntimeState([&](RuntimeState& state) {
        auto* participant = UpsertRemoteParticipant(
            state,
            packet.participant_id,
            ParticipantControllerKind::Native);
        if (participant == nullptr) {
            return;
        }

        auto& progression =
            participant->owned_progression;
        if (packet.spellbook_revision <
                progression.spellbook_revision ||
            packet.statbook_revision <
                progression.statbook_revision) {
            return;
        }
        progression.initialized = true;
        progression.spellbook_revision =
            packet.spellbook_revision;
        progression.statbook_revision =
            packet.statbook_revision;
        progression.progression_book_entry_total_count =
            packet.entry_total_count;
        progression.progression_book_truncated =
            (packet.snapshot_flags &
             ParticipantProgressionBookSnapshotFlagTruncated) != 0;
        progression.progression_book_entries.clear();
        progression.progression_book_entries.reserve(
            packet.entry_count);
        for (std::size_t index = 0;
             index < packet.entry_count;
             ++index) {
            const auto& packet_entry =
                packet.entries[index];
            ParticipantProgressionBookEntryState entry;
            entry.entry_index = packet_entry.entry_index;
            entry.internal_id = packet_entry.internal_id;
            entry.active = packet_entry.active;
            entry.visible = packet_entry.visible;
            entry.category = packet_entry.category;
            entry.statbook_max_level =
                packet_entry.statbook_max_level;
            progression.progression_book_entries.push_back(
                entry);
        }
    });
}

void SendLocalParticipantProgressionSnapshots(
    const std::vector<TransportPeerEndpoint>& endpoints,
    std::uint64_t now_ms) {
    auto& checkpoints =
        g_local_transport
            .participant_progression_send_checkpoints;
    checkpoints.erase(
        std::remove_if(
            checkpoints.begin(),
            checkpoints.end(),
            [&](const ParticipantProgressionSendCheckpoint&
                    checkpoint) {
                return std::none_of(
                    endpoints.begin(),
                    endpoints.end(),
                    [&](const TransportPeerEndpoint& endpoint) {
                        return SameEndpoint(
                            checkpoint.endpoint,
                            endpoint);
                    });
            }),
        checkpoints.end());

    const auto runtime_state = SnapshotRuntimeState();
    const auto* local = FindLocalParticipant(runtime_state);
    if (local == nullptr) {
        return;
    }

    ParticipantInventorySnapshotPacket inventory_packet{};
    bool inventory_packet_built = false;
    ParticipantProgressionBookSnapshotPacket
        progression_book_packet{};
    bool progression_book_packet_built = false;
    for (const auto& endpoint : endpoints) {
        auto checkpoint = std::find_if(
            checkpoints.begin(),
            checkpoints.end(),
            [&](const ParticipantProgressionSendCheckpoint&
                    candidate) {
                return SameEndpoint(
                    candidate.endpoint,
                    endpoint);
            });
        if (checkpoint == checkpoints.end()) {
            ParticipantProgressionSendCheckpoint added;
            added.endpoint = endpoint;
            checkpoints.push_back(added);
            checkpoint = std::prev(checkpoints.end());
        }

        const bool inventory_due =
            !checkpoint->inventory_sent ||
            checkpoint->inventory_revision !=
                local->owned_progression.inventory_revision ||
            now_ms < checkpoint->inventory_sent_ms ||
            now_ms - checkpoint->inventory_sent_ms >=
                kParticipantProgressionReliableCheckpointIntervalMs;
        if (inventory_due) {
            if (!inventory_packet_built) {
                inventory_packet_built =
                    BuildLocalParticipantInventorySnapshotPacket(
                        &inventory_packet);
            }
            if (inventory_packet_built) {
                SendBufferToEndpoint(
                    &inventory_packet,
                    ParticipantInventorySnapshotPacketWireSize(
                        inventory_packet.item_count),
                    endpoint,
                    SteamNetworkSendMode::ReliableNoNagle);
                checkpoint->inventory_sent = true;
                checkpoint->inventory_revision =
                    inventory_packet.inventory_revision;
                checkpoint->inventory_sent_ms = now_ms;
            }
        }

        const bool progression_book_due =
            !checkpoint->progression_book_sent ||
            checkpoint->spellbook_revision !=
                local->owned_progression.spellbook_revision ||
            checkpoint->statbook_revision !=
                local->owned_progression.statbook_revision ||
            now_ms < checkpoint->progression_book_sent_ms ||
            now_ms -
                    checkpoint->progression_book_sent_ms >=
                kParticipantProgressionReliableCheckpointIntervalMs;
        if (!progression_book_due) {
            continue;
        }
        if (!progression_book_packet_built) {
            progression_book_packet_built =
                BuildLocalParticipantProgressionBookSnapshotPacket(
                    &progression_book_packet);
        }
        if (!progression_book_packet_built) {
            continue;
        }
        SendBufferToEndpoint(
            &progression_book_packet,
            ParticipantProgressionBookSnapshotPacketWireSize(
                progression_book_packet.entry_count),
            endpoint,
            SteamNetworkSendMode::ReliableNoNagle);
        checkpoint->progression_book_sent = true;
        checkpoint->spellbook_revision =
            progression_book_packet.spellbook_revision;
        checkpoint->statbook_revision =
            progression_book_packet.statbook_revision;
        checkpoint->progression_book_sent_ms = now_ms;
    }
}
