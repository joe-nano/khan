""" energy server handles json requests to compute energy and gradient """ 


from khan.training.trainer_multi_tower import TrainerMultiTower, initialize_module
from khan.data.dataset import RawDataset
import data_utils
from analyze_errors import fdiff_grad
import tensorflow as tf
import argparse
import os
import sys
import numpy as np
import json
import client_server

KCAL = 627.509
BOHR = 0.52917721092 
ENCODING = 'utf-8'

MAX_BYTES = 1024**2

def parse_args(args):
    """
    Parse commandline arguments and return a namespace
    """

    parser = argparse.ArgumentParser(
        description="server for energy requests",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--work-dir",
        default="~/work",
        help="location of saved NN"
    )
    parser.add_argument(
        "--ani_lib",
        default="/Users/jacobson/projects/ani1_training/khan/gpu_featurizer/ani_cpu.so", 
        help="Location of shared object"
    )
    parser.add_argument(
        "--host",
        action="store",
        default="nyc-mbp-jacobson.local",
        help="host name for energy server"
    )
    
    parser.add_argument(
        "--port",
        action="store",
        default=5000,
        type=int,
        help="port for energy server"
    )

    parser.add_argument(
        '--deep_network',
        action='store_true',
        help='Use James super deep network (256, 256, 256, 256, 256, 256, 256, 128, 64, 8, 1)'
    )

    parser.add_argument(
        '--gaussian-activation',
        action='store_true',
        help='Use gaussian activation functions'
    )

    parser.add_argument(
        '--fit-charges',
        action='store_true',
        help='fit charges'
    )

    parser.add_argument(
        "--fdiff_grad",
        action="store_true",
        default=False,
        help="finite difference the gradients"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="print some debugging info"
    )
    
    args = parser.parse_args()

    return args


def main():

    args = parse_args(sys.argv)
    lib_path = os.path.abspath(args.ani_lib)
    initialize_module(lib_path)

    save_dir = os.path.join(args.work_dir, "save")

    config = tf.ConfigProto(allow_soft_placement=True)
    with tf.Session(config=config) as sess:

        layer_sizes = (128, 128, 64, 1)
        if args.deep_network:
            layer_sizes = (256, 256, 256, 256, 256, 256, 256, 128, 64, 8, 1)
        towers = ["/cpu:0"]
        print("start with layers", layer_sizes)
        trainer = TrainerMultiTower(
            sess,
            towers,
            layer_sizes=layer_sizes,
            fit_charges=args.fit_charges,
            gaussian_activation=args.gaussian_activation
        )

        trainer.load(save_dir)

        s = client_server.connect_socket(args.host, args.port, server=True)

        if args.debug:
            print("Server listening on port %d" % args.port)

        while True:

            if args.debug:
                print("awaiting connection...")

            conn, addr = s.accept()

            if args.debug:
                print("Connection established...")
            
            while True:

                rcv_data = client_server.recieve(conn)

                print("recieved data", rcv_data)

                if rcv_data:

                    X = json.loads(rcv_data).get('X') 
                    X_np = np.array(X, dtype=np.float32)
                    rd = RawDataset([X_np], [0.0])

                    # should I go back to total energy?
                    energy = float(trainer.predict(rd)[0])
                    self_interaction = sum(
                        data_utils.selfIxnNrgWB97X_631gdp[example[0]] for example in X
                    )
                    energy += self_interaction

                    gradient = list(trainer.coordinate_gradients(rd))[0]
                    natoms, ndim = gradient.shape
                    gradient = gradient.reshape(natoms*ndim)

                    if args.fdiff_grad:
                        fd_gradient = fdiff_grad(X_np, trainer)
                        dg = gradient - fd_gradient
                        grms = np.sqrt(sum(dg[:]**2.0)/(natoms*ndim))
                        dot = np.dot(gradient, fd_gradient) 
                        norm_g = np.sqrt(np.dot(gradient, gradient))
                        norm_fd = np.sqrt(np.dot(fd_gradient, fd_gradient))
                        dot = np.dot(gradient, fd_gradient) / (norm_fd * norm_g)
                        gradient[:] = fd_gradient[:]
                        print("RMS gradient fdiff/analytic %.4e" % grms)
                        print("Gradient dot product %.4f" % dot)

                    # convert gradient from hartree/angstrom to hartree/bohr
                    # and to jsonable format
                    gradient = [float(g)*BOHR for g in gradient]

                    print("sending gradient")
                    print(gradient)

                    send_data = json.dumps({"energy": energy, "gradient": gradient})

                    print("sending response...")

                    client_server.send(conn, send_data)

                else:
                    break

if __name__ == "__main__":
    main()

