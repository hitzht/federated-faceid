import multiprocessing
from multiprocessing import Pipe
from multiprocessing.connection import wait
from typing import *

import numpy as np
import torch
from torch import optim, Tensor
from torch.nn import functional, Module
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from torchvision.datasets import CIFAR10

from models import federated as fd
from models.baseline import CNNCifar10
from utils import constants, data
from utils.settings import Settings, args_parser


def test(net_g, data_loader):
    # testing
    net_g.eval()
    test_loss = 0
    correct = 0
    l = len(data_loader)
    for idx, (data, target) in enumerate(data_loader):
        log_probs = net_g(data)
        test_loss += functional.cross_entropy(log_probs, target).item()
        y_pred = log_probs.data.max(1, keepdim=True)[1]
        correct += y_pred.eq(target.data.view_as(y_pred)).long().cpu().sum()

    test_loss /= len(data_loader.dataset)
    print('\nTest set: Average loss: {:.4f} \nAccuracy: {}/{} ({:.2f}%)\n'.format(
        test_loss, correct, len(data_loader.dataset),
        100. * correct / len(data_loader.dataset)))

    return correct, test_loss


def train():
    # parse args
    settings: Settings = args_parser()
    settings.device = torch.device("cuda:0" if torch.cuda.is_available() else 'cpu')
    torch.manual_seed(settings.seed)

    # load dataset and split users
    transform = transforms.Compose([transforms.ToTensor(),
                                    transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
    dataset_train = CIFAR10(constants.PATH_DATASET_CIFAR10,
                            train=True, transform=transform, download=True)

    model: torch.nn.Module = CNNCifar10()
    model.to(settings.device)
    train_federated(model, dataset_train, settings)

    # dataset_test = CIFAR10(constants.PATH_DATASET_CIFAR10,
    #                        train=False, transform=transform, download=True)
    # test_loader = DataLoader(dataset_test, batch_size=settings.num_global_batch, shuffle=False)
    # print('test on', len(dataset_test), 'samples')
    # test_acc, test_loss = test(model.cpu(), test_loader)


def train_federated(model: Module, dataset: CIFAR10, settings: Settings) -> Module:
    num_users: int = len(dataset.classes)
    class_to_idx = dataset.class_to_idx
    idx_to_class = {v: k for k, v in class_to_idx.items()}

    settings_edge_device = fd.EdgeDeviceSettings(epochs=settings.num_local_epochs,
                                                 batch_size=settings.num_local_batch,
                                                 learning_rate=settings.learning_rate,
                                                 device=settings.device)

    subsets: List[CIFAR10]
    if settings.iid:
        subsets = data.split_dataset_iid(dataset, num_users)
    else:
        subsets = data.split_dataset_non_iid(dataset)

    device_connections: Dict[int, fd.EdgeDeviceConnection] = {}
    for device_name in dataset.classes:
        device_id = class_to_idx[device_name]
        handle_server, handle_device = Pipe(duplex=True)
        device = fd.EdgeDevice(name=device_name,
                               handle=handle_server,
                               dataset=subsets[device_id],
                               settings=settings_edge_device)
        device_connections[device_id] = fd.EdgeDeviceConnection(handle=handle_device,
                                                                process=device)
        device.start()

    for i_epoch in range(settings.num_global_epochs):
        local_models: Dict[int, Module] = {}
        local_losses: Dict[int, float] = {}

        users_in_round_ids = np.random.choice(range(num_users),
                                              constants.MAX_USERS_IN_ROUND,
                                              replace=False)

        device_connections_in_round = {i: device_connections[i] for i in users_in_round_ids}

        for device_id, device_connection in device_connections_in_round.items():
            print(f"[server] Sending model to {idx_to_class[device_id]}")
            device_connection.handle.send(model)

        # for device_id, device_connection in device_connections_in_round.items():
        #     handle = wait([device_connection.handle])[0]
        while len(local_losses) != len(device_connections_in_round):
            handles = [c.handle for c in device_connections_in_round.values()]
            for handle in wait(handles):
                device_result: fd.EdgeDeviceResult = handle.recv()

                print(f"[server] Receiving model form {device_result.name}")
                device_id = class_to_idx[device_result.name]
                local_models[device_id] = device_result.model
                local_losses[device_id] = device_result.loss

        # update global weights
        model = fd.federated_averaging(list(local_models.values()))

        loss_avg = sum(list(local_losses.values())) / len(local_losses)
        print('Round {:3d}, Average loss {:.3f}'.format(i_epoch, loss_avg))

    for device_id, device_connection in device_connections.items():
        print(f"[server] Terminating {idx_to_class[device_id]}")
        device_connection.process.terminate()

    return model


def train_server(model: Module, dataset: Dataset, settings: Settings) -> Module:
    dataset_iter = DataLoader(dataset, batch_size=settings.num_global_batch,
                              shuffle=True)
    optimizer = optim.SGD(model.parameters(), lr=settings.learning_rate)

    list_loss = []
    model.train()
    for i_epoch in range(settings.num_global_epochs):
        batch_loss = []
        for i_batch, (data, target) in enumerate(dataset_iter):
            optimizer.zero_grad()
            data = data.to(settings.device)
            target = target.to(settings.device)

            output: Tensor = model(data)
            loss: Tensor = functional.cross_entropy(output, target)
            loss.backward()
            optimizer.step()

            if i_batch % 50 == 0:
                print(f"Train Epoch: {i_epoch}"
                      f"[{i_batch * len(data)}/{len(dataset_iter.dataset)} "
                      f"({100.0 * i_batch / len(dataset_iter):.0f}%)]"
                      f"\tLoss: {loss.item():.6f}")
            batch_loss.append(loss.item())

        loss_avg = sum(batch_loss) / len(batch_loss)
        print('\nTrain loss:', loss_avg)
        list_loss.append(loss_avg)
    return model


if __name__ == '__main__':
    multiprocessing.set_start_method(constants.PROCESS_START_METHOD)
    train()
