export { default as InitialNode } from "./InitialNode";
export { default as MessageNode } from "./MessageNode";
export { default as CollectSlotNode } from "./CollectSlotNode";
export { default as CollectFormNode } from "./CollectFormNode";
export { default as APIRequestNode } from "./APIRequestNode";
export { default as ConditionNode } from "./ConditionNode";
export { default as RouterNode } from "./RouterNode";
export { default as ConfirmationNode } from "./ConfirmationNode";
export { default as SetVariableNode } from "./SetVariableNode";
export { default as SaveRecordNode } from "./SaveRecordNode";
export { default as TransferNode } from "./TransferNode";
export { default as CapabilityNode } from "./CapabilityNode";
export { default as EndNode } from "./EndNode";

import InitialNode from "./InitialNode";
import MessageNode from "./MessageNode";
import CollectSlotNode from "./CollectSlotNode";
import CollectFormNode from "./CollectFormNode";
import APIRequestNode from "./APIRequestNode";
import ConditionNode from "./ConditionNode";
import RouterNode from "./RouterNode";
import ConfirmationNode from "./ConfirmationNode";
import SetVariableNode from "./SetVariableNode";
import SaveRecordNode from "./SaveRecordNode";
import TransferNode from "./TransferNode";
import CapabilityNode from "./CapabilityNode";
import EndNode from "./EndNode";

export const nodeTypes = {
  initial: InitialNode,
  message: MessageNode,
  collect_slot: CollectSlotNode,
  collect_form: CollectFormNode,
  api_request: APIRequestNode,
  condition: ConditionNode,
  router: RouterNode,
  confirmation: ConfirmationNode,
  set_variable: SetVariableNode,
  save_record: SaveRecordNode,
  transfer: TransferNode,
  capability: CapabilityNode,
  end: EndNode,
};
