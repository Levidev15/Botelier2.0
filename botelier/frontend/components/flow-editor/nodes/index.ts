export { default as InitialNode } from "./InitialNode";
export { default as MessageNode } from "./MessageNode";
export { default as CollectSlotNode } from "./CollectSlotNode";
export { default as APIRequestNode } from "./APIRequestNode";
export { default as ConditionNode } from "./ConditionNode";
export { default as RouterNode } from "./RouterNode";
export { default as ConfirmationNode } from "./ConfirmationNode";
export { default as SetVariableNode } from "./SetVariableNode";
export { default as TransferNode } from "./TransferNode";
export { default as EndNode } from "./EndNode";

import InitialNode from "./InitialNode";
import MessageNode from "./MessageNode";
import CollectSlotNode from "./CollectSlotNode";
import APIRequestNode from "./APIRequestNode";
import ConditionNode from "./ConditionNode";
import RouterNode from "./RouterNode";
import ConfirmationNode from "./ConfirmationNode";
import SetVariableNode from "./SetVariableNode";
import TransferNode from "./TransferNode";
import EndNode from "./EndNode";

export const nodeTypes = {
  initial: InitialNode,
  message: MessageNode,
  collect_slot: CollectSlotNode,
  api_request: APIRequestNode,
  condition: ConditionNode,
  router: RouterNode,
  confirmation: ConfirmationNode,
  set_variable: SetVariableNode,
  transfer: TransferNode,
  end: EndNode,
};
